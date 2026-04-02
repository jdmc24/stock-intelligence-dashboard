from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import engine, get_session
from app.models import AnalysisResult, Base, Transcript
from app.schemas import CompanySummary, CompanyTimelineOut, TimelinePoint
from app.services.comparison_runner import quarter_sort_key

router = APIRouter(prefix="/api/earnings/companies", tags=["companies"])


async def _ensure_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _loads(s: str | None) -> dict[str, Any] | None:
    if not s:
        return None
    try:
        o = json.loads(s)
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        return None


def _timeline_point(t: Transcript, ar: AnalysisResult) -> TimelinePoint:
    sent = _loads(ar.sentiment_json) or {}
    hed = _loads(ar.hedging_json) or {}
    guid = _loads(ar.guidance_json) or {}
    top = _loads(ar.topics_json) or {}

    overall = sent.get("overall_tone") if isinstance(sent.get("overall_tone"), str) else None

    hs = hed.get("hedging_score")
    hedging_score = float(hs) if isinstance(hs, (int, float)) else None

    glist = guid.get("guidance") if isinstance(guid, dict) else None
    guidance_count = len(glist) if isinstance(glist, list) else 0

    topic_names: list[str] = []
    topics_list = top.get("topics") if isinstance(top, dict) else None
    if isinstance(topics_list, list):
        scored: list[tuple[float, str]] = []
        for item in topics_list:
            if not isinstance(item, dict):
                continue
            name = item.get("topic")
            if not isinstance(name, str):
                continue
            rel = item.get("relevance")
            r = float(rel) if isinstance(rel, (int, float)) else 0.0
            scored.append((r, name))
        scored.sort(key=lambda x: -x[0])
        topic_names = [n for _, n in scored[:8]]

    return TimelinePoint(
        transcript_id=t.id,
        quarter=t.quarter,
        call_date=t.call_date,
        overall_tone=overall,
        hedging_score=hedging_score,
        guidance_count=guidance_count,
        top_topics=topic_names,
    )


@router.get("", dependencies=[Depends(require_bearer_token)], response_model=list[CompanySummary])
async def list_companies(session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    res = await session.execute(select(Transcript))
    rows = list(res.scalars().all())
    by: dict[str, list[Transcript]] = {}
    for t in rows:
        by.setdefault(t.ticker.upper(), []).append(t)
    out: list[CompanySummary] = []
    for ticker in sorted(by.keys()):
        items = by[ticker]
        cn = next((x.company_name for x in items if x.company_name), None)
        out.append(CompanySummary(ticker=ticker, company_name=cn, transcript_count=len(items)))
    return out


@router.get("/{ticker}/timeline", dependencies=[Depends(require_bearer_token)], response_model=CompanyTimelineOut)
async def company_timeline(ticker: str, session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    t_up = ticker.strip().upper()
    res = await session.execute(select(Transcript).where(func.upper(Transcript.ticker) == t_up))
    transcripts = list(res.scalars().all())
    if not transcripts:
        raise HTTPException(status_code=404, detail="No transcripts for this ticker")

    company_name = next((x.company_name for x in transcripts if x.company_name), None)
    ordered = sorted(transcripts, key=quarter_sort_key)

    points: list[TimelinePoint] = []
    for t in ordered:
        if t.status != "analyzed":
            continue
        ar_res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == t.id))
        ar = ar_res.scalar_one_or_none()
        if ar is None or ar.status != "complete":
            continue
        points.append(_timeline_point(t, ar))

    return CompanyTimelineOut(ticker=t_up, company_name=company_name, points=points)
