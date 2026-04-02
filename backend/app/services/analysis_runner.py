from __future__ import annotations

import asyncio
import datetime as dt
import json

from sqlalchemy import select

from app.db import session_context
from app.models import AnalysisResult, Transcript
from app.prompts import analysis_prompts as prompts
from app.services.llm.anthropic_client import complete_json
from app.settings import settings

MAX_TRANSCRIPT_CHARS = 120_000


def _truncate(text: str) -> str:
    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text
    return text[:MAX_TRANSCRIPT_CHARS] + "\n\n[...truncated for analysis...]"


async def run_analysis(transcript_id: str) -> None:
    """Load transcript, run four LLM extractions, persist AnalysisResult."""
    async with session_context() as session:
        t = await session.get(Transcript, transcript_id)
        if t is None or t.status == "error":
            return

        res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
        row = res.scalar_one_or_none()
        if row is None:
            row = AnalysisResult(transcript_id=transcript_id, status="processing")
            session.add(row)
        else:
            row.status = "processing"
            row.error_message = None
        await session.commit()

        ticker = t.ticker
        company_name = t.company_name
        quarter = t.quarter
        body = _truncate(t.raw_text)

    user_prefix = prompts.transcript_block(
        ticker=ticker,
        company_name=company_name,
        quarter=quarter,
        text=body,
    )

    try:
        sentiment, hedging, guidance, topics = await asyncio.gather(
            asyncio.to_thread(
                complete_json,
                prompts.SENTIMENT_SYSTEM,
                user_prefix + "\n\nAnalyze sentiment per section. If the transcript is one blob, use one section.",
            ),
            asyncio.to_thread(
                complete_json,
                prompts.HEDGING_SYSTEM,
                user_prefix + "\n\nFlag hedging language instances.",
            ),
            asyncio.to_thread(
                complete_json,
                prompts.GUIDANCE_SYSTEM,
                user_prefix + "\n\nExtract forward-looking guidance.",
            ),
            asyncio.to_thread(
                complete_json,
                prompts.TOPICS_SYSTEM,
                user_prefix + "\n\nTag topics from the taxonomy.",
            ),
        )

        summary = ""
        if isinstance(sentiment, dict):
            summary = str(sentiment.get("executive_summary") or "") or str(
                sentiment.get("overall_tone") or ""
            )

        async with session_context() as session:
            row2 = (
                await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
            ).scalar_one_or_none()
            if row2 is None:
                return
            row2.status = "complete"
            row2.error_message = None
            row2.summary = summary or None
            row2.sentiment_json = json.dumps(sentiment, ensure_ascii=False)
            row2.hedging_json = json.dumps(hedging, ensure_ascii=False)
            row2.guidance_json = json.dumps(guidance, ensure_ascii=False)
            row2.topics_json = json.dumps(topics, ensure_ascii=False)
            row2.model_used = settings.anthropic_model
            row2.updated_at = dt.datetime.now(dt.UTC)

            tr = await session.get(Transcript, transcript_id)
            if tr:
                tr.status = "analyzed"
            await session.commit()
    except Exception as e:
        async with session_context() as session:
            row3 = (
                await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
            ).scalar_one_or_none()
            if row3:
                row3.status = "error"
                row3.error_message = str(e)
                row3.updated_at = dt.datetime.now(dt.UTC)
                await session.commit()
