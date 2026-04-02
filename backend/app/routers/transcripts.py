from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import engine, get_session, session_context
from app.models import Base, Transcript, TranscriptSection
from app.schemas import TranscriptFetchIn, TranscriptFetchOut, TranscriptOut, TranscriptUploadIn
from app.services.earningscall_client import EarningsCallError, fetch_transcript as earningscall_fetch_transcript
from app.services.transcript_parser import parse_sections

router = APIRouter(prefix="/api/earnings/transcripts", tags=["transcripts"])


async def _ensure_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _to_out(t: Transcript, sections: list[TranscriptSection]) -> TranscriptOut:
    return TranscriptOut(
        id=t.id,
        ticker=t.ticker,
        company_name=t.company_name,
        quarter=t.quarter,
        call_date=t.call_date,
        source=t.source,  # type: ignore[arg-type]
        source_url=t.source_url,
        raw_text=t.raw_text,
        status=t.status,  # type: ignore[arg-type]
        error_message=t.error_message,
        created_at=t.created_at,
        processed_at=t.processed_at,
        sections=[
            {
                "id": s.id,
                "transcript_id": s.transcript_id,
                "section_type": s.section_type,
                "speaker": s.speaker,
                "text": s.text,
                "order": s.order,
            }
            for s in sorted(sections, key=lambda x: x.order)
        ],
    )


async def _background_fetch_and_parse(transcript_id: str) -> None:
    await _ensure_db()
    async with session_context() as session:
        t = await session.get(Transcript, transcript_id)
        if t is None:
            return
        t.status = "processing"
        t.error_message = None
        await session.commit()

    try:
        text, company_name, source_url, speaker_segments = await earningscall_fetch_transcript(
            ticker=t.ticker, quarter_label=t.quarter
        )

        if speaker_segments:
            sections = []
            for i, seg in enumerate(speaker_segments):
                sec_type = "qa" if seg.get("is_qa") else "prepared_remarks"
                sections.append(
                    {
                        "section_type": sec_type,
                        "speaker": seg.get("speaker"),
                        "text": seg.get("text") or "",
                        "order": i,
                    }
                )
        else:
            sections = parse_sections(text)

        async with session_context() as session:
            t2 = await session.get(Transcript, transcript_id)
            if t2 is None:
                return
            t2.raw_text = text
            t2.source_url = source_url
            if company_name and not t2.company_name:
                t2.company_name = company_name
            t2.status = "raw"
            t2.processed_at = dt.datetime.now(dt.UTC)

            await session.execute(delete(TranscriptSection).where(TranscriptSection.transcript_id == transcript_id))
            for s in sections:
                session.add(
                    TranscriptSection(
                        transcript_id=transcript_id,
                        section_type=s["section_type"],
                        speaker=s["speaker"],
                        text=s["text"],
                        order=s["order"],
                    )
                )

            await session.commit()
    except Exception as e:
        async with session_context() as session:
            t3 = await session.get(Transcript, transcript_id)
            if t3 is None:
                return
            t3.status = "error"
            t3.error_message = str(e)
            await session.commit()


@router.post("/fetch", dependencies=[Depends(require_bearer_token)], response_model=TranscriptFetchOut)
async def fetch_transcript(
    body: TranscriptFetchIn,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    await _ensure_db()
    ticker = body.ticker.strip().upper()
    quarter = body.quarter.strip() if body.quarter else None

    t = Transcript(
        ticker=ticker,
        quarter=quarter,
        source="earningscall",
        source_url=None,
        raw_text="",
        status="processing",
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)

    background.add_task(_background_fetch_and_parse, t.id)
    return TranscriptFetchOut(transcript_id=t.id, status=t.status)  # type: ignore[arg-type]


@router.post("/upload", dependencies=[Depends(require_bearer_token)], response_model=TranscriptFetchOut)
async def upload_transcript(
    body: TranscriptUploadIn,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    await _ensure_db()
    ticker = body.ticker.strip().upper()
    quarter = body.quarter.strip() if body.quarter else None
    t = Transcript(
        ticker=ticker,
        quarter=quarter,
        company_name=body.company_name,
        call_date=body.call_date,
        source="upload",
        source_url=None,
        raw_text=body.raw_text,
        status="processing",
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)

    async def _background_parse_only(transcript_id: str) -> None:
        await _ensure_db()
        try:
            sections = parse_sections(body.raw_text)
            async with session_context() as s2:
                await s2.execute(delete(TranscriptSection).where(TranscriptSection.transcript_id == transcript_id))
                for sec in sections:
                    s2.add(
                        TranscriptSection(
                            transcript_id=transcript_id,
                            section_type=sec["section_type"],
                            speaker=sec["speaker"],
                            text=sec["text"],
                            order=sec["order"],
                        )
                    )
                t2 = await s2.get(Transcript, transcript_id)
                if t2:
                    t2.status = "raw"
                    t2.processed_at = dt.datetime.now(dt.UTC)
                await s2.commit()
        except Exception as e:
            async with session_context() as s2:
                t2 = await s2.get(Transcript, transcript_id)
                if t2:
                    t2.status = "error"
                    t2.error_message = str(e)
                await s2.commit()

    background.add_task(_background_parse_only, t.id)
    return TranscriptFetchOut(transcript_id=t.id, status=t.status)  # type: ignore[arg-type]


@router.get("", dependencies=[Depends(require_bearer_token)], response_model=list[TranscriptOut])
async def list_transcripts(
    session: AsyncSession = Depends(get_session),
    ticker: str | None = Query(default=None, max_length=16, description="Filter by ticker (exact)"),
    status: str | None = Query(default=None, max_length=24, description='e.g. "analyzed"'),
    limit: int = Query(default=50, ge=1, le=200, description="Max rows (default 50; raise for compare flows)"),
):
    await _ensure_db()
    conds: list = []
    if ticker and ticker.strip():
        conds.append(func.upper(Transcript.ticker) == ticker.strip().upper())
    if status and status.strip():
        conds.append(Transcript.status == status.strip())
    stmt = select(Transcript).order_by(Transcript.created_at.desc()).limit(limit)
    if conds:
        stmt = select(Transcript).where(*conds).order_by(Transcript.created_at.desc()).limit(limit)
    res = await session.execute(stmt)
    transcripts = list(res.scalars().all())
    out: list[TranscriptOut] = []
    for t in transcripts:
        res2 = await session.execute(
            select(TranscriptSection).where(TranscriptSection.transcript_id == t.id).order_by(TranscriptSection.order.asc())
        )
        out.append(_to_out(t, list(res2.scalars().all())))
    return out


@router.get("/{transcript_id}", dependencies=[Depends(require_bearer_token)], response_model=TranscriptOut)
async def get_transcript(transcript_id: str, session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    t = await session.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    res2 = await session.execute(
        select(TranscriptSection).where(TranscriptSection.transcript_id == t.id).order_by(TranscriptSection.order.asc())
    )
    return _to_out(t, list(res2.scalars().all()))


@router.delete("/{transcript_id}", dependencies=[Depends(require_bearer_token)])
async def delete_transcript(transcript_id: str, session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    t = await session.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    await session.delete(t)
    await session.commit()
    return {"ok": True}

