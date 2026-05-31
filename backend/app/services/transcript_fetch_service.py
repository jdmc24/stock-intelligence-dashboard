from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transcript, TranscriptSection
from app.services.analysis_runner import run_analysis
from app.services.earningscall_client import EarningsCallError, fetch_transcript as earningscall_fetch_transcript
from app.services.transcript_parser import parse_sections
from app.settings import settings

logger = logging.getLogger(__name__)

_USABLE_STATUSES = frozenset({"raw", "analyzed"})


def _sections_from_speaker_segments(speaker_segments: list[dict] | None, text: str) -> list[dict[str, Any]]:
    if speaker_segments:
        sections: list[dict[str, Any]] = []
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
        return sections
    return parse_sections(text)


async def _usable_transcript_count(session: AsyncSession, ticker: str) -> int:
    t_up = ticker.strip().upper()
    res = await session.execute(
        select(func.count())
        .select_from(Transcript)
        .where(
            func.upper(Transcript.ticker) == t_up,
            Transcript.status.in_(_USABLE_STATUSES),
            func.length(Transcript.raw_text) > 100,
        )
    )
    return int(res.scalar_one() or 0)


async def apply_fetch_result(
    session: AsyncSession,
    transcript: Transcript,
    *,
    text: str,
    company_name: str | None,
    source_url: str | None,
    speaker_segments: list[dict] | None,
    quarter_label: str | None,
) -> None:
    sections = _sections_from_speaker_segments(speaker_segments, text)
    transcript.raw_text = text
    transcript.source_url = source_url
    if company_name and not transcript.company_name:
        transcript.company_name = company_name
    if quarter_label and not transcript.quarter:
        transcript.quarter = quarter_label
    transcript.status = "raw"
    transcript.error_message = None
    transcript.processed_at = dt.datetime.now(dt.UTC)

    await session.execute(delete(TranscriptSection).where(TranscriptSection.transcript_id == transcript.id))
    for s in sections:
        session.add(
            TranscriptSection(
                transcript_id=transcript.id,
                section_type=s["section_type"],
                speaker=s["speaker"],
                text=s["text"],
                order=s["order"],
            )
        )


async def fetch_transcript_into_db(
    session: AsyncSession,
    ticker: str,
    quarter: str | None = None,
) -> Transcript:
    """Fetch one earnings call from EarningsCall and persist transcript + sections."""
    t_up = ticker.strip().upper()
    if not t_up:
        raise EarningsCallError("empty ticker")

    transcript = Transcript(
        ticker=t_up,
        quarter=quarter.strip() if quarter else None,
        source="earningscall",
        source_url=None,
        raw_text="",
        status="processing",
    )
    session.add(transcript)
    await session.flush()

    try:
        text, company_name, source_url, speaker_segments, resolved_quarter = await earningscall_fetch_transcript(
            ticker=t_up,
            quarter_label=transcript.quarter,
        )
        await apply_fetch_result(
            session,
            transcript,
            text=text,
            company_name=company_name,
            source_url=source_url,
            speaker_segments=speaker_segments,
            quarter_label=resolved_quarter,
        )
        await session.commit()
        await session.refresh(transcript)
        return transcript
    except Exception as e:
        transcript.status = "error"
        transcript.error_message = str(e)
        await session.commit()
        raise


async def ensure_transcripts_for_ticker(
    session: AsyncSession,
    ticker: str,
    *,
    min_count: int = 1,
    run_analysis: bool = True,
) -> tuple[list[Transcript], list[str]]:
    """Ensure stored transcripts exist for Ask / earnings tools.

    Fetches the latest call from EarningsCall when none are stored locally.
    Optionally runs AI analysis so timeline and analysis tools have data.
    """
    t_up = (ticker or "").strip().upper()
    notes: list[str] = []
    if not t_up:
        return [], notes

    have = await _usable_transcript_count(session, t_up)
    if have >= max(1, min_count):
        res = await session.execute(
            select(Transcript)
            .where(
                func.upper(Transcript.ticker) == t_up,
                Transcript.status.in_(_USABLE_STATUSES),
                func.length(Transcript.raw_text) > 100,
            )
            .order_by(Transcript.created_at.desc())
            .limit(min_count)
        )
        return list(res.scalars().all()), notes

    try:
        transcript = await fetch_transcript_into_db(session, t_up)
    except EarningsCallError as e:
        notes.append(f"Could not fetch {t_up} earnings transcript: {e}")
        return [], notes
    except Exception as e:
        logger.exception("unexpected transcript fetch failure for %s", t_up)
        notes.append(f"Could not fetch {t_up} earnings transcript: {e}")
        return [], notes

    q_label = transcript.quarter or "latest quarter"
    notes.append(f"Fetched {t_up} {q_label} earnings transcript from EarningsCall.")

    if run_analysis and settings.anthropic_api_key and transcript.status == "raw":
        notes.append(f"Analyzing {t_up} {q_label} call — this may take a moment…")
        await run_analysis(transcript.id)
        await session.refresh(transcript)
        if transcript.status == "analyzed":
            notes.append(f"Analysis complete for {t_up} {q_label}.")
        else:
            notes.append(
                f"Transcript fetched for {t_up}, but analysis did not finish — quote search still works."
            )
    elif transcript.status == "raw":
        notes.append(
            f"Transcript stored for {t_up}; set ANTHROPIC_API_KEY for structured call analysis."
        )

    return [transcript], notes
