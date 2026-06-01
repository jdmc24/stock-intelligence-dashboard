from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transcript, TranscriptSection
from app.services.analysis_runner import run_analysis as run_transcript_analysis
from app.services.earningscall_client import (
    EarningsCallError,
    candidate_quarters,
    fetch_transcript as earningscall_fetch_transcript,
    normalize_earnings_ticker,
)
from app.services.transcript_parser import parse_sections
from app.settings import settings

logger = logging.getLogger(__name__)

_USABLE_STATUSES = frozenset({"raw", "analyzed"})

# Ask orchestrator: pre-load this many recent calls per ticker (not an LLM tool — runs before the agent).
ASK_EARNINGS_MIN_TRANSCRIPTS = 4
ASK_EARNINGS_MAX_FETCH_PER_RUN = 4


def _quarter_label(year: int, quarter: int) -> str:
    return f"Q{quarter}-{year}"


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
    t_up = normalize_earnings_ticker(ticker)
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


async def _stored_quarter_labels(session: AsyncSession, ticker: str) -> set[str]:
    t_up = normalize_earnings_ticker(ticker)
    res = await session.execute(
        select(Transcript.quarter).where(
            func.upper(Transcript.ticker) == t_up,
            Transcript.status.in_(_USABLE_STATUSES),
            func.length(Transcript.raw_text) > 100,
        )
    )
    out: set[str] = set()
    for label in res.scalars().all():
        if isinstance(label, str) and label.strip():
            out.add(label.strip())
    return out


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
    t_up = normalize_earnings_ticker(ticker)
    if not t_up:
        raise EarningsCallError("empty ticker")

    text, company_name, source_url, speaker_segments, resolved_quarter = await earningscall_fetch_transcript(
        ticker=t_up,
        quarter_label=quarter.strip() if quarter else None,
    )

    transcript = Transcript(
        ticker=t_up,
        quarter=resolved_quarter or (quarter.strip() if quarter else None),
        company_name=company_name,
        source="earningscall",
        source_url=source_url,
        raw_text=text,
        status="raw",
        processed_at=dt.datetime.now(dt.UTC),
    )
    session.add(transcript)
    await session.flush()
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


async def fetch_next_missing_quarter(
    session: AsyncSession,
    ticker: str,
    *,
    stored_labels: set[str] | None = None,
) -> Transcript | None:
    """Fetch the next recent quarter from EarningsCall that is not already stored."""
    t_up = normalize_earnings_ticker(ticker)
    if not t_up:
        return None
    have = stored_labels if stored_labels is not None else await _stored_quarter_labels(session, t_up)

    for spec in candidate_quarters(back=12):
        label = _quarter_label(spec.year, spec.quarter)
        if label in have:
            continue
        try:
            tr = await fetch_transcript_into_db(session, t_up, quarter=label)
            have.add(label)
            return tr
        except EarningsCallError as e:
            logger.info("no transcript for %s %s: %s", t_up, label, e)
            continue
    return None


async def _analyze_newest_raw(session: AsyncSession, ticker: str) -> str | None:
    t_up = normalize_earnings_ticker(ticker)
    res = await session.execute(
        select(Transcript)
        .where(
            func.upper(Transcript.ticker) == t_up,
            Transcript.status == "raw",
            func.length(Transcript.raw_text) > 100,
        )
        .order_by(Transcript.created_at.desc())
        .limit(1)
    )
    raw = res.scalar_one_or_none()
    if raw is None:
        return None
    q_label = raw.quarter or "latest quarter"
    await run_transcript_analysis(raw.id)
    await session.refresh(raw)
    if raw.status == "analyzed":
        return f"Analysis complete for {t_up} {q_label}."
    return f"Transcript stored for {t_up} {q_label}, but analysis did not finish — quote search still works."


async def ensure_transcripts_for_ticker(
    session: AsyncSession,
    ticker: str,
    *,
    min_count: int = ASK_EARNINGS_MIN_TRANSCRIPTS,
    max_fetch: int = ASK_EARNINGS_MAX_FETCH_PER_RUN,
    run_analysis: bool = True,
) -> tuple[list[Transcript], list[str]]:
    """Ensure stored transcripts exist for Ask / earnings tools.

    Pulls up to `max_fetch` missing recent quarters from EarningsCall when below
    `min_count`. Runs AI analysis on the newest call only (quote search works on all raw calls).
    """
    notes: list[str] = []
    t_up = normalize_earnings_ticker(ticker)
    if not t_up:
        return [], notes

    target = max(1, min(int(min_count), 12))
    cap = max(1, min(int(max_fetch), 12))
    stored = await _stored_quarter_labels(session, t_up)
    fetched: list[Transcript] = []

    attempts = 0
    while await _usable_transcript_count(session, t_up) < target and attempts < cap:
        tr = await fetch_next_missing_quarter(session, t_up, stored_labels=stored)
        if tr is None:
            break
        fetched.append(tr)
        attempts += 1
        q_label = tr.quarter or "latest quarter"
        notes.append(f"Fetched {t_up} {q_label} earnings transcript from EarningsCall.")
        if tr.quarter:
            stored.add(tr.quarter)

    res = await session.execute(
        select(Transcript)
        .where(
            func.upper(Transcript.ticker) == t_up,
            Transcript.status.in_(_USABLE_STATUSES),
            func.length(Transcript.raw_text) > 100,
        )
        .order_by(Transcript.created_at.desc())
        .limit(target)
    )
    transcripts = list(res.scalars().all())

    if len(transcripts) >= 2:
        quarters = ", ".join(t.quarter or "?" for t in transcripts[:4])
        notes.append(f"{t_up}: {len(transcripts)} earnings call(s) available for Ask ({quarters}).")

    if not fetched and not transcripts:
        try:
            tr = await fetch_transcript_into_db(session, t_up)
            transcripts = [tr]
            q_label = tr.quarter or "latest quarter"
            notes.append(f"Fetched {t_up} {q_label} earnings transcript from EarningsCall.")
        except EarningsCallError as e:
            notes.append(f"Could not fetch {t_up} earnings transcript: {e}")
            return [], notes

    if run_analysis and settings.anthropic_api_key and transcripts:
        notes.append("Analyzing the most recent call — this may take a moment…")
        analysis_note = await _analyze_newest_raw(session, t_up)
        if analysis_note:
            notes.append(analysis_note)
    elif transcripts and not settings.anthropic_api_key:
        notes.append(f"Stored {len(transcripts)} call(s) for {t_up}; set ANTHROPIC_API_KEY for structured analysis.")

    return transcripts, notes
