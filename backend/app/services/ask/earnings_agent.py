from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.ask_prompts import EARNINGS_AGENT_SYSTEM
from app.services.ask.earnings_tools import ASK_EARNINGS_TOOLS, run_tool_with_events
from app.services.llm.anthropic_client import complete_json_with_tools_and_usage
from app.settings import settings

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def run_earnings_agent(
    session: AsyncSession,
    *,
    question: str,
    intent: dict[str, Any],
    emit: EventCallback,
    emitter: Any,
) -> tuple[dict[str, Any], int, int]:
    """Earnings specialist: tool loop → structured research brief."""

    async def emit_tool_start(name: str, inp: dict[str, Any]) -> None:
        await emit(
            emitter.next(
                "tool_start",
                agent="earnings",
                tool=name,
                input=inp,
            )
        )

    async def emit_tool_end(
        name: str,
        inp: dict[str, Any],
        output: dict[str, Any],
        is_error: bool,
        duration_ms: int,
    ) -> None:
        await emit(
            emitter.next(
                "tool_end",
                agent="earnings",
                tool=name,
                input=inp,
                output=_trim_tool_output(output),
                is_error=is_error,
                duration_ms=duration_ms,
            )
        )

    async def tool_dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_events(session, name, args or {}, emit_tool_start, emit_tool_end)

    user = _build_agent_user(question, intent)

    if not settings.anthropic_api_key:
        brief = await _deterministic_brief(session, intent, emit_tool_start, emit_tool_end)
        return brief, 0, 0

    try:
        parsed, _tool_log, in_t, out_t = await complete_json_with_tools_and_usage(
            EARNINGS_AGENT_SYSTEM,
            user,
            ASK_EARNINGS_TOOLS,
            execute_tool_async=tool_dispatch,
            max_iters=5,
            max_tokens=4096,
        )
        return parsed, in_t, out_t
    except ValueError as e:
        if "JSON object" not in str(e):
            raise
        brief = await _deterministic_brief(session, intent, emit_tool_start, emit_tool_end)
        gaps = list(brief.get("gaps") or [])
        gaps.append("LLM earnings brief parse failed — used deterministic tool results.")
        brief["gaps"] = gaps
        return brief, 0, 0


def _build_agent_user(question: str, intent: dict[str, Any]) -> str:
    tickers = intent.get("tickers") or []
    topics = intent.get("topics") or []
    hint = ""
    if tickers:
        hint += f"\nPrimary ticker(s): {', '.join(str(t).upper() for t in tickers)}\n"
    if topics:
        hint += f"Topics to probe on calls: {', '.join(str(t) for t in topics)}\n"
    return (
        f"User question:\n{question.strip()}\n\n"
        f"Parsed intent (orchestrator):\n{json.dumps(intent, indent=2)}\n"
        f"{hint}\n"
        "Start with list_transcripts_for_ticker or company_earnings_timeline when a ticker is known. "
        "Use search_transcript_quotes for how executives discussed specific themes."
    )


def _trim_tool_output(output: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(output, default=str)
    if len(text) <= 4000:
        return output
    return {"note": "output truncated for stream", "preview": text[:3500] + "…"}


async def _deterministic_brief(
    session: AsyncSession,
    intent: dict[str, Any],
    emit_tool_start: Any,
    emit_tool_end: Any,
) -> dict[str, Any]:
    tickers = [str(t).upper() for t in (intent.get("tickers") or []) if t]
    topics = intent.get("topics") or []
    key_transcripts: list[dict[str, Any]] = []
    quotes: list[dict[str, Any]] = []
    gaps: list[str] = ["LLM earnings research unavailable without ANTHROPIC_API_KEY"]

    if not tickers:
        return {
            "research_summary": "No ticker identified for earnings research.",
            "tickers": [],
            "key_transcripts": [],
            "notable_quotes": [],
            "narrative_themes": [],
            "gaps": [*gaps, "Name a company ticker to search stored earnings calls."],
        }

    ticker = tickers[0]
    timeline = await run_tool_with_events(
        session,
        "company_earnings_timeline",
        {"ticker": ticker},
        emit_tool_start,
        emit_tool_end,
    )
    listing = await run_tool_with_events(
        session,
        "list_transcripts_for_ticker",
        {"ticker": ticker, "limit": 3},
        emit_tool_start,
        emit_tool_end,
    )

    for tr in (listing.get("transcripts") or [])[:2]:
        tid = tr.get("transcript_id")
        if not tid:
            continue
        analysis = await run_tool_with_events(
            session,
            "get_transcript_analysis",
            {"transcript_id": str(tid)},
            emit_tool_start,
            emit_tool_end,
        )
        if analysis.get("status") == "complete":
            key_transcripts.append(
                {
                    "transcript_id": tid,
                    "ticker": analysis.get("ticker"),
                    "quarter": analysis.get("quarter"),
                    "summary_excerpt": (analysis.get("summary") or "")[:400],
                    "overall_tone": analysis.get("overall_tone"),
                    "top_topics": [t.get("topic") for t in (analysis.get("top_topics") or []) if t.get("topic")],
                }
            )

    query = " ".join(str(t) for t in topics[:2]) if topics else "outlook"
    quote_hits = await run_tool_with_events(
        session,
        "search_transcript_quotes",
        {"query": query, "company": ticker},
        emit_tool_start,
        emit_tool_end,
    )
    for q in (quote_hits.get("quotes") or [])[:3]:
        quotes.append(q)

    if not key_transcripts and not (timeline.get("points") or []):
        gaps.append(f"No analyzed earnings calls stored for {ticker}.")

    return {
        "research_summary": (
            f"Deterministic earnings scan for {ticker} (ANTHROPIC_API_KEY not set). "
            f"Found {len(key_transcripts)} analyzed call(s) with structured themes."
        ),
        "tickers": tickers,
        "key_transcripts": key_transcripts,
        "notable_quotes": quotes,
        "narrative_themes": _themes_from_timeline(timeline),
        "timeline_point_count": timeline.get("analyzed_call_count") or 0,
        "gaps": gaps,
    }


def _themes_from_timeline(timeline: dict[str, Any]) -> list[str]:
    themes: list[str] = []
    for pt in (timeline.get("points") or [])[-3:]:
        for name in pt.get("top_topics") or []:
            if isinstance(name, str) and name not in themes:
                themes.append(name)
    return themes[:8]
