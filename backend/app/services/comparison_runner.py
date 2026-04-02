from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from sqlalchemy import select

from app.db import session_context
from app.models import AnalysisResult, Transcript
from app.prompts import comparison_prompts as prompts
from app.services.llm.anthropic_client import complete_json

DIMENSION_SET = frozenset({"sentiment", "hedging", "guidance", "topics"})


def quarter_sort_key(t: Transcript) -> tuple:
    if t.call_date:
        return (t.call_date.isoformat(), t.quarter or "", t.created_at.isoformat())
    q = t.quarter or ""
    m = re.match(r"Q(\d)-(\d{4})", q.strip(), re.I)
    if m:
        qn, yr = int(m.group(1)), int(m.group(2))
        return (f"{yr:04d}-{qn:02d}", q, t.created_at.isoformat())
    return (q, t.created_at.isoformat())


def _loads(s: str | None) -> dict[str, Any] | None:
    if not s:
        return None
    try:
        o = json.loads(s)
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        return None


def _filter_dimensions(blob: dict[str, Any], dimensions: frozenset[str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "transcript_id": blob["transcript_id"],
        "quarter": blob.get("quarter"),
        "call_date": blob.get("call_date"),
    }
    if "sentiment" in dimensions and blob.get("sentiment") is not None:
        out["sentiment"] = blob["sentiment"]
    if "hedging" in dimensions and blob.get("hedging") is not None:
        out["hedging"] = blob["hedging"]
    if "guidance" in dimensions and blob.get("guidance") is not None:
        out["guidance"] = blob["guidance"]
    if "topics" in dimensions and blob.get("topics") is not None:
        out["topics"] = blob["topics"]
    return out


async def run_comparison(
    transcript_ids: list[str],
    dimensions: list[str] | None,
) -> dict[str, Any]:
    """Load completed analyses, validate same company, call LLM once."""
    if len(transcript_ids) < 2:
        raise ValueError("Need at least two transcript ids")

    dims = frozenset(d.lower() for d in dimensions) & DIMENSION_SET if dimensions else DIMENSION_SET
    if not dims:
        dims = DIMENSION_SET

    async with session_context() as session:
        pairs: list[tuple[Transcript, AnalysisResult]] = []
        for tid in transcript_ids:
            t = await session.get(Transcript, tid)
            if t is None:
                raise ValueError(f"Transcript not found: {tid}")
            res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == tid))
            ar = res.scalar_one_or_none()
            if ar is None or ar.status != "complete":
                raise ValueError(f"Analysis not complete for transcript: {tid}")
            if t.status != "analyzed":
                raise ValueError(f"Transcript not analyzed: {tid}")
            pairs.append((t, ar))

    tickers = {p[0].ticker.upper() for p in pairs}
    if len(tickers) != 1:
        raise ValueError("All transcripts must be for the same ticker")

    pairs.sort(key=lambda x: quarter_sort_key(x[0]))
    company_name = next((p[0].company_name for p in pairs if p[0].company_name), None)
    ticker = pairs[0][0].ticker.upper()

    quarters_payload: list[dict[str, Any]] = []
    for t, ar in pairs:
        blob: dict[str, Any] = {
            "transcript_id": t.id,
            "quarter": t.quarter,
            "call_date": t.call_date.isoformat() if t.call_date else None,
            "sentiment": _loads(ar.sentiment_json),
            "hedging": _loads(ar.hedging_json),
            "guidance": _loads(ar.guidance_json),
            "topics": _loads(ar.topics_json),
        }
        quarters_payload.append(_filter_dimensions(blob, dims))

    user = prompts.analyses_block(ticker, company_name, quarters_payload)
    user += "\nCompare these quarters. Name quarters in evidence using the quarter labels provided."

    result = await asyncio.to_thread(complete_json, prompts.COMPARISON_SYSTEM, user)
    if not isinstance(result, dict):
        raise RuntimeError("Model returned non-object JSON")
    return result
