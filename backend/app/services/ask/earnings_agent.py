from __future__ import annotations

import re
import time
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transcript
from app.services.ask.earnings_filings import EarningsFiling
from app.services.ask.earnings_tools import run_tool_with_events

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]

_TOPIC = re.compile(
    r"\b(?:about|discuss(?:ed)?|mention(?:ed)?|comment(?:s|ed)? on)\s+(.+?)"
    r"(?=\s+(?:on|during|in|from|over|across|at|since)\s+(?:(?:the|its|their)\s+)?"
    r"(?:latest|last|most recent|this|previous|recent|Q[1-4]|\d{4}|earnings|conference|the call)\b|[?.!,;]|$)",
    re.IGNORECASE,
)


_CALL_SCOPE = re.compile(
    r"^(?:(?:the|its|their|this|that|a|an)\s+)?"
    r"(?:(?:latest|last|most recent|recent|previous|next|quarterly|first[ -]quarter|second[ -]quarter|third[ -]quarter|fourth[ -]quarter|q[1-4]|20\d{2})[\s-]+)*"
    r"(?:earnings(?: (?:conference )?calls?)?|conference calls?|calls?|transcripts?|results)\b",
    re.IGNORECASE,
)
_OPERATOR_HANDOFF = re.compile(r"\bplease go ahead[.!]\s+", re.IGNORECASE)


def _question_topic(question: str) -> str:
    for match in _TOPIC.finditer(question):
        topic = match[1].strip()
        if not _CALL_SCOPE.match(topic) and not re.fullmatch(
            r"(?:Q[1-4]|(?:the )?(?:first|second|third|fourth)[ -]quarter)(?:[ -]20\d{2})?", topic, re.I
        ):
            return topic
    return ""


def _overview_passages(text: str, limit: int, size: int) -> list[str]:
    handoff = _OPERATOR_HANDOFF.search(text, 0, min(len(text), 1600))
    if handoff:
        text = text[handoff.end():].strip()
    if len(text) <= limit * size:
        return [text[i:i + size] for i in range(0, len(text), size)]
    # Sample the whole call, with more coverage near the start of prepared remarks.
    offsets = [int((len(text) - size) * (i / max(limit - 1, 1)) ** 1.7) for i in range(limit)]
    return [text[i:i + size].strip() for i in offsets]


def _topic_passages(text: str, topic: str, limit: int, size: int) -> list[str]:
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(rf"(?<!\w){re.escape(topic)}(?!\w)", text, re.IGNORECASE):
        if ranges and match.start() < ranges[-1][1]:
            continue
        ranges.append((max(0, match.start() - size // 3), match.end() + 2 * size // 3))
        if len(ranges) == limit:
            break
    return [text[start:end].strip() for start, end in ranges]


async def run_earnings_agent(
    session: AsyncSession,
    *,
    question: str,
    intent: dict[str, Any],
    transcripts: list[Transcript],
    filings: list[EarningsFiling],
    emit: EventCallback,
    emitter: Any,
) -> dict[str, Any]:
    """Build evidence from the transcripts selected by the orchestrator."""
    async def tool_start(name: str, inputs: dict[str, Any]) -> None:
        await emit(emitter.next("tool_start", agent="earnings", tool=name, input=inputs))

    async def tool_end(
        name: str, inputs: dict[str, Any], output: dict[str, Any], is_error: bool, duration_ms: int
    ) -> None:
        await emit(emitter.next(
            "tool_end", agent="earnings", tool=name, input=inputs, output=output,
            is_error=is_error, duration_ms=duration_ms,
        ))

    key_transcripts = []
    passages_by_call = []
    quotes = []
    timeline_points = []
    gaps = list(intent.get("prefetch_notes") or [])
    topic = _question_topic(question)
    searched = {"topic": topic, "transcript_ids": [tr.id for tr in transcripts]}
    if transcripts:
        started = time.monotonic()
        await tool_start("read_earnings_transcripts", searched)
        limit = min(7, max(1, 20 // len(transcripts)))
        size = min(2700, 24000 // (len(transcripts) * limit))
        topic_matches = 0
        for tr in transcripts:
            text = " ".join(tr.raw_text.split())
            key_transcripts.append({
                "transcript_id": tr.id,
                "ticker": tr.ticker,
                "quarter": tr.quarter,
                "call_date": tr.call_date.isoformat() if tr.call_date else None,
                "has_analysis": tr.status == "analyzed",
            })
            selected = _topic_passages(text, topic, limit, size) if topic else []
            topic_matches += len(selected)
            if not selected:
                selected = _overview_passages(text, limit, size)
            passages_by_call.append([
                {"transcript_id": tr.id, "ticker": tr.ticker, "quarter": tr.quarter, "excerpt": passage}
                for passage in selected
            ])
        # Interleave calls so comparisons retain evidence for each issuer and quarter.
        quotes = [
            passages[index]
            for index in range(limit)
            for passages in passages_by_call
            if index < len(passages)
        ]
        await tool_end(
            "read_earnings_transcripts", searched,
            {"found": bool(quotes), "count": len(quotes), "transcript_count": len(transcripts),
             "topic_match_count": topic_matches},
            False, int((time.monotonic() - started) * 1000),
        )
        if topic and not topic_matches:
            gaps.append(f'No exact mention of "{topic}" was found. The research brief includes general call passages.')

    if intent.get("is_earnings_drift"):
        for ticker in dict.fromkeys(tr.ticker for tr in transcripts):
            timeline = await run_tool_with_events(
                session, "company_earnings_timeline", {"ticker": ticker}, tool_start, tool_end
            )
            transcript_ids = {tr.id for tr in transcripts}
            timeline_points.extend(
                point for point in timeline.get("points", []) if point.get("transcript_id") in transcript_ids
            )

    key_filings = []
    for filing in filings:
        size = min(7500, 12000 // len(filings))
        targeted = _topic_passages(filing.text, topic, 2, 1000) if topic else []
        key_filings.append({
            "ticker": filing.ticker,
            "quarter": filing.quarter,
            "kind": filing.kind,
            "label": filing.label,
            "url": filing.url,
            "accession": filing.accession,
            "period_end": filing.period_end.isoformat(),
            "excerpts": [filing.text[:size], *targeted],
        })
    summary = f"Retrieved {len(transcripts)} earnings call transcript(s)." if transcripts else (
        "No earnings transcript was available for this question."
    )
    if filings:
        summary += f" Retrieved {len(filings)} issuer filing(s) as fallback evidence."
    return {
        "research_summary": summary,
        "tickers": list(dict.fromkeys(item.ticker for item in [*transcripts, *filings])),
        "key_transcripts": key_transcripts,
        "key_filings": key_filings,
        "notable_quotes": quotes,
        "timeline_points": timeline_points,
        "timeline_point_count": len(timeline_points),
        "gaps": gaps,
    }
