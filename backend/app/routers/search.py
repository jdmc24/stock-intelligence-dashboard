from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import engine, get_session
from app.models import Base, Transcript, TranscriptSection
from app.schemas import QuoteHit, SearchHit

router = APIRouter(prefix="/api/earnings/search", tags=["search"])


async def _ensure_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _snippet(text: str, needle: str, radius: int = 90) -> str:
    if not text:
        return ""
    n = needle.strip().lower()
    if not n:
        tail = text[:220]
        return tail + ("…" if len(text) > 220 else "")
    low = text.lower()
    idx = low.find(n)
    if idx < 0:
        tail = text[:220]
        return tail + ("…" if len(text) > 220 else "")
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    out = text[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


@router.get("", dependencies=[Depends(require_bearer_token)], response_model=list[SearchHit])
async def search_transcripts(
    company: str | None = Query(default=None, max_length=16, description="Ticker filter (exact match)"),
    topic: str | None = Query(default=None, max_length=128, description="Substring match in full transcript text"),
    q: str | None = Query(default=None, max_length=256, description="Keyword in full transcript text"),
    session: AsyncSession = Depends(get_session),
):
    """Search stored transcripts by ticker and/or text content."""
    await _ensure_db()
    c = company.strip() if company else None
    t = topic.strip() if topic else None
    qq = q.strip() if q else None
    if not c and not t and not qq:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: company, topic, q",
        )

    conds = []
    if c:
        conds.append(func.upper(Transcript.ticker) == c.upper())
    if t:
        conds.append(func.instr(func.lower(Transcript.raw_text), t.lower()) > 0)
    if qq:
        conds.append(func.instr(func.lower(Transcript.raw_text), qq.lower()) > 0)

    stmt = select(Transcript).where(*conds).order_by(Transcript.created_at.desc()).limit(40)
    res = await session.execute(stmt)
    rows = list(res.scalars().all())

    needle = qq or t or ""
    out: list[SearchHit] = []
    for tr in rows:
        out.append(
            SearchHit(
                transcript_id=tr.id,
                ticker=tr.ticker,
                quarter=tr.quarter,
                company_name=tr.company_name,
                status=tr.status,  # type: ignore[arg-type]
                snippet=_snippet(tr.raw_text, needle),
            )
        )
    return out


@router.get("/quotes", dependencies=[Depends(require_bearer_token)], response_model=list[QuoteHit])
async def search_quotes(
    query: str = Query(..., min_length=2, max_length=256, description="Phrase to find in section text"),
    company: str | None = Query(default=None, max_length=16, description="Optional ticker filter"),
    session: AsyncSession = Depends(get_session),
):
    """Find speaker sections whose text contains the query."""
    await _ensure_db()
    qn = query.strip()
    conds = [func.instr(func.lower(TranscriptSection.text), qn.lower()) > 0]
    if company and company.strip():
        conds.append(func.upper(Transcript.ticker) == company.strip().upper())

    stmt = (
        select(TranscriptSection, Transcript)
        .join(Transcript, TranscriptSection.transcript_id == Transcript.id)
        .where(*conds)
        .order_by(Transcript.created_at.desc(), TranscriptSection.order.asc())
        .limit(50)
    )
    res = await session.execute(stmt)
    pairs = list(res.all())

    out: list[QuoteHit] = []
    for sec, tr in pairs:
        out.append(
            QuoteHit(
                transcript_id=tr.id,
                ticker=tr.ticker,
                quarter=tr.quarter,
                section_type=sec.section_type,  # type: ignore[arg-type]
                speaker=sec.speaker,
                excerpt=_snippet(sec.text, qn, radius=120),
                order=sec.order,
            )
        )
    return out
