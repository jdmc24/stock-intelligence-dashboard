from __future__ import annotations

import re
import time
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transcript
from app.services.ask.earnings_tools import _snippet, run_tool_with_events

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]

_TOPIC = re.compile(
    r"\b(?:about|discuss(?:ed)?|mention(?:ed)?|comment(?:s|ed)? on)\s+(.+?)"
    r"(?=\s+(?:on|during|in|over|across|at|for|since)\b|[?.!,;]|$)",
    re.IGNORECASE,
)


async def run_earnings_agent(
    session: AsyncSession,
    *,
    question: str,
    intent: dict[str, Any],
    transcripts: list[Transcript],
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
    quotes = []
    timeline_points = []
    gaps = list(intent.get("prefetch_notes") or [])
    topic_match = _TOPIC.search(question)
    topic = topic_match[1].strip() if topic_match else ""
    searched = {"topic": topic, "transcript_ids": [tr.id for tr in transcripts]}
    if transcripts:
        started = time.monotonic()
        await tool_start("read_earnings_transcripts", searched)
        for tr in transcripts:
            text = " ".join(tr.raw_text.split())
            key_transcripts.append({
                "transcript_id": tr.id,
                "ticker": tr.ticker,
                "quarter": tr.quarter,
                "has_analysis": tr.status == "analyzed",
                "transcript_excerpt": _snippet(text, ""),
            })
            if topic:
                matches = list(re.finditer(rf"(?<!\w){re.escape(topic)}(?!\w)", text, re.IGNORECASE))
                passages = [text[max(0, m.start() - 350):m.end() + 450] for m in matches[:3]]
            else:
                size = 1200
                offsets = [0, len(text) // 2, len(text) - size] if len(text) > size * 3 else [0]
                passages = [text[offset:offset + size] for offset in offsets] if len(offsets) > 1 else [text[:size * 3]]
            for passage in passages:
                quotes.append({
                    "transcript_id": tr.id, "ticker": tr.ticker, "quarter": tr.quarter, "excerpt": passage,
                })

        await tool_end(
            "read_earnings_transcripts", searched, {"found": True, "count": len(transcripts)}, False,
            int((time.monotonic() - started) * 1000),
        )
        if topic and not quotes:
            gaps.append(f'No exact mention of "{topic}" was found in the selected transcript text.')

    if intent.get("is_earnings_drift"):
        for ticker in dict.fromkeys(tr.ticker for tr in transcripts):
            timeline = await run_tool_with_events(
                session, "company_earnings_timeline", {"ticker": ticker}, tool_start, tool_end
            )
            transcript_ids = {tr.id for tr in transcripts}
            timeline_points.extend(
                point for point in timeline.get("points", []) if point.get("transcript_id") in transcript_ids
            )

    summary = f"Retrieved {len(transcripts)} earnings call transcript(s)." if transcripts else (
        "No earnings transcript was available for this question."
    )
    return {
        "research_summary": summary,
        "tickers": list(dict.fromkeys(tr.ticker for tr in transcripts)),
        "key_transcripts": key_transcripts,
        "notable_quotes": quotes,
        "timeline_points": timeline_points,
        "timeline_point_count": len(timeline_points),
        "gaps": gaps,
    }
