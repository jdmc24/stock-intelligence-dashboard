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
from app.services.edgar_client import EdgarClient, EdgarError
from app.services.sec_ticker_registry import search_sec_companies
from app.services.comparison_runner import quarter_sort_key
from app.services.transcript_parser import parse_sections
from app.settings import settings

logger = logging.getLogger(__name__)

class TranscriptFetchError(RuntimeError):
    """Neither EarningsCall nor SEC EDGAR returned a usable transcript."""

_USABLE_STATUSES = frozenset({"raw", "analyzed"})

# Ask orchestrator transcript backfill (not an LLM tool — runs before the earnings agent).
# STORED_TARGET: quarters we aim to keep per ticker (~8 years) for trend / quote search.
# MAX_FETCH_PER_RUN: new EarningsCall fetches per Ask run (incremental backfill, keeps latency reasonable).
# QUARTER_LOOKBACK: how far back to scan when hunting missing quarters.
ASK_EARNINGS_STORED_TARGET = 32
ASK_EARNINGS_MAX_FETCH_PER_RUN = 12
ASK_EARNINGS_QUARTER_LOOKBACK = 40

# Backward-compatible alias used in older references
ASK_EARNINGS_MIN_TRANSCRIPTS = ASK_EARNINGS_STORED_TARGET


def _quarter_label(year: int, quarter: int) -> str:
    return f"Q{quarter}-{year}"


def ask_prefetch_targets(question: str, *, ticker_count: int = 1) -> tuple[int, int, bool]:
    """Return (stored_target, max_fetch, run_analysis) for this question.

    stored_target: quarters we want on file for the ticker.
    max_fetch: cap new EarningsCall pulls this run (incremental backfill).
    run_analysis: whether to run four-pass LLM analysis on the newest call during prefetch
    (skipped for compare questions — quote search works on raw text; saves minutes).
    """
    q = (question or "").lower()
    is_compare = any(
        hint in q
        for hint in (
            "compare",
            "comparison",
            "versus",
            " vs ",
            " vs.",
            "side by side",
            "head to head",
        )
    )

    if is_compare and ticker_count >= 2:
        return 4, 3, False
    if is_compare:
        return 6, 4, False

    if any(
        hint in q
        for hint in (
            "over time",
            "over the last",
            "several calls",
            "multiple calls",
            "history",
            "trend",
            "years",
            "quarters",
        )
    ):
        return ASK_EARNINGS_STORED_TARGET, ASK_EARNINGS_MAX_FETCH_PER_RUN, True

    if any(
        hint in q
        for hint in (
            "latest",
            "most recent",
            "last quarter",
            "recent quarter",
            "last call",
            "recent call",
        )
    ):
        return 2, 6, True

    return 8, 6, True


async def _company_name_for_ticker(ticker: str) -> str | None:
    hits = await search_sec_companies(ticker, limit=1)
    if not hits:
        return None
    name = hits[0].get("company_name")
    return str(name) if name else None


async def _fetch_from_edgar(
    ticker: str,
    quarter_label: str | None = None,
) -> tuple[str, str | None, str | None, list[dict] | None, str | None]:
    t_up = normalize_earnings_ticker(ticker)
    client = EdgarClient()
    try:
        text, source_url = await client.fetch_best_transcript_text(t_up, quarter_label)
    finally:
        await client.aclose()

    company_name = await _company_name_for_ticker(t_up)
    resolved_quarter = quarter_label or _quarter_label(
        dt.date.today().year,
        (dt.date.today().month - 1) // 3 + 1,
    )
    return text, company_name, source_url, None, resolved_quarter


async def _persist_transcript(
    session: AsyncSession,
    *,
    ticker: str,
    source: str,
    text: str,
    company_name: str | None,
    source_url: str | None,
    speaker_segments: list[dict] | None,
    quarter_label: str | None,
) -> Transcript:
    t_up = normalize_earnings_ticker(ticker)
    transcript = Transcript(
        ticker=t_up,
        quarter=quarter_label,
        company_name=company_name,
        source=source,
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
        quarter_label=quarter_label,
    )
    await session.commit()
    await session.refresh(transcript)
    return transcript


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
    *,
    earningscall_only: bool = False,
) -> Transcript:
    """Fetch one earnings call, preferring EarningsCall then SEC EDGAR."""
    t_up = normalize_earnings_ticker(ticker)
    if not t_up:
        raise TranscriptFetchError("empty ticker")

    quarter_label = quarter.strip() if quarter else None
    errors: list[str] = []

    if settings.earningcall_api_key:
        try:
            text, company_name, source_url, speaker_segments, resolved_quarter = await earningscall_fetch_transcript(
                ticker=t_up,
                quarter_label=quarter_label,
            )
            return await _persist_transcript(
                session,
                ticker=t_up,
                source="earningscall",
                text=text,
                company_name=company_name,
                source_url=source_url,
                speaker_segments=speaker_segments,
                quarter_label=resolved_quarter or quarter_label,
            )
        except EarningsCallError as e:
            errors.append(f"EarningsCall: {e}")
            logger.info("EarningsCall fetch failed for %s: %s", t_up, e)
    else:
        errors.append("EarningsCall: EARNINGSCALL_API_KEY not set")

    if earningscall_only:
        raise TranscriptFetchError(
            f"Could not fetch {t_up} earnings transcript. " + " ".join(errors)
        )

    try:
        text, company_name, source_url, speaker_segments, resolved_quarter = await _fetch_from_edgar(
            t_up,
            quarter_label,
        )
        return await _persist_transcript(
            session,
            ticker=t_up,
            source="edgar",
            text=text,
            company_name=company_name,
            source_url=source_url,
            speaker_segments=speaker_segments,
            quarter_label=resolved_quarter or quarter_label,
        )
    except EdgarError as e:
        errors.append(f"SEC EDGAR: {e}")
        logger.info("EDGAR fetch failed for %s: %s", t_up, e)

    raise TranscriptFetchError(
        f"Could not fetch {t_up} earnings transcript. " + " ".join(errors)
    )


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

    for spec in candidate_quarters(back=ASK_EARNINGS_QUARTER_LOOKBACK):
        label = _quarter_label(spec.year, spec.quarter)
        if label in have:
            continue
        try:
            tr = await fetch_transcript_into_db(session, t_up, quarter=label, earningscall_only=True)
            have.add(label)
            return tr
        except (EarningsCallError, TranscriptFetchError) as e:
            logger.info("no transcript for %s %s: %s", t_up, label, e)
            continue
    return None


def _sort_transcripts_newest_first(transcripts: list[Transcript]) -> list[Transcript]:
    return sorted(transcripts, key=quarter_sort_key, reverse=True)


async def _load_usable_transcripts(session: AsyncSession, ticker: str) -> list[Transcript]:
    t_up = normalize_earnings_ticker(ticker)
    res = await session.execute(
        select(Transcript).where(
            func.upper(Transcript.ticker) == t_up,
            Transcript.status.in_(_USABLE_STATUSES),
            func.length(Transcript.raw_text) > 100,
        )
    )
    return _sort_transcripts_newest_first(list(res.scalars().all()))


async def _analyze_newest_raw(session: AsyncSession, ticker: str) -> str | None:
    t_up = normalize_earnings_ticker(ticker)
    ordered = await _load_usable_transcripts(session, t_up)
    if not ordered:
        return None

    newest = ordered[0]
    q_label = newest.quarter or "latest quarter"

    if newest.status == "analyzed":
        return f"Most recent call {t_up} {q_label} is already analyzed."

    await run_transcript_analysis(newest.id)
    await session.refresh(newest)
    if newest.status == "analyzed":
        return f"Analysis complete for {t_up} {q_label}."
    return f"Transcript stored for {t_up} {q_label}, but analysis did not finish — quote search still works."


async def ensure_transcripts_for_ticker(
    session: AsyncSession,
    ticker: str,
    *,
    min_count: int = ASK_EARNINGS_STORED_TARGET,
    max_fetch: int = ASK_EARNINGS_MAX_FETCH_PER_RUN,
    run_analysis: bool = True,
) -> tuple[list[Transcript], list[str]]:
    """Ensure stored transcripts exist for Ask / earnings tools.

    Pulls missing recent quarters from EarningsCall when configured, then falls back to
    SEC EDGAR (latest 8-K exhibit) when needed. Runs AI analysis on the newest call only.
    """
    notes: list[str] = []
    t_up = normalize_earnings_ticker(ticker)
    if not t_up:
        return [], notes

    max_quarters = ASK_EARNINGS_STORED_TARGET
    target = max(1, min(int(min_count), max_quarters))
    cap = max(1, min(int(max_fetch), max_quarters))
    stored = await _stored_quarter_labels(session, t_up)
    fetched: list[Transcript] = []

    attempts = 0
    if settings.earningcall_api_key and target > 1:
        while await _usable_transcript_count(session, t_up) < target and attempts < cap:
            tr = await fetch_next_missing_quarter(session, t_up, stored_labels=stored)
            if tr is None:
                break
            fetched.append(tr)
            attempts += 1
            q_label = tr.quarter or "latest quarter"
            source_label = "EarningsCall" if tr.source == "earningscall" else "SEC EDGAR"
            notes.append(f"Fetched {t_up} {q_label} earnings transcript from {source_label}.")
            if tr.quarter:
                stored.add(tr.quarter)
    elif not settings.earningcall_api_key and target > 1:
        notes.append(
            f"{t_up}: EARNINGSCALL_API_KEY not set — skipping multi-quarter backfill; will try SEC EDGAR for the latest call."
        )

    if await _usable_transcript_count(session, t_up) < max(1, min(target, 1)):
        try:
            tr = await fetch_transcript_into_db(session, t_up)
            if tr not in fetched:
                fetched.append(tr)
            q_label = tr.quarter or "latest quarter"
            source_label = "EarningsCall" if tr.source == "earningscall" else "SEC EDGAR"
            notes.append(f"Fetched {t_up} {q_label} earnings transcript from {source_label}.")
        except TranscriptFetchError as e:
            notes.append(f"Could not fetch {t_up} earnings transcript: {e}")
            return [], notes

    transcripts = (await _load_usable_transcripts(session, t_up))[:target]

    if len(transcripts) >= 2:
        shown = transcripts[:6]
        quarters = ", ".join(t.quarter or "?" for t in shown)
        extra = len(transcripts) - len(shown)
        suffix = f", +{extra} more" if extra > 0 else ""
        notes.append(f"{t_up}: {len(transcripts)} earnings call(s) available for Ask ({quarters}{suffix}).")
    elif len(transcripts) == 1:
        q_label = transcripts[0].quarter or "latest quarter"
        notes.append(
            f"{t_up}: analysis can use {q_label} now. "
            f"Ask can load up to {ASK_EARNINGS_STORED_TARGET} recent quarters — "
            f"ask how a theme changed over several calls to pull more history."
        )

    if not fetched and not transcripts:
        notes.append(f"No earnings transcripts available for {t_up} from EarningsCall or SEC EDGAR.")
        return [], notes

    if run_analysis and settings.anthropic_api_key and transcripts:
        notes.append("Analyzing the most recent call — this may take a moment…")
        analysis_note = await _analyze_newest_raw(session, t_up)
        if analysis_note:
            notes.append(analysis_note)
    elif transcripts and not settings.anthropic_api_key:
        notes.append(f"Stored {len(transcripts)} call(s) for {t_up}; set ANTHROPIC_API_KEY for structured analysis.")

    return transcripts, notes
