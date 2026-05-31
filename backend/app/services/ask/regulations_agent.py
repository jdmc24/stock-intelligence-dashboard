from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.ask_prompts import REGULATIONS_AGENT_SYSTEM
from app.services.ask.regulations_tools import ASK_REG_TOOLS, run_tool_with_events
from app.services.llm.anthropic_client import complete_json_with_tools_and_usage
from app.settings import settings

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def run_regulations_agent(
    session: AsyncSession,
    *,
    question: str,
    intent: dict[str, Any],
    lookback_days: int,
    emit: EventCallback,
    emitter: Any,
) -> tuple[dict[str, Any], int, int]:
    """Regulations specialist: tool loop → structured research brief."""

    async def emit_tool_start(name: str, inp: dict[str, Any]) -> None:
        await emit(
            emitter.next(
                "tool_start",
                agent="regulations",
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
                agent="regulations",
                tool=name,
                input=inp,
                output=_trim_tool_output(output),
                is_error=is_error,
                duration_ms=duration_ms,
            )
        )

    async def tool_dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "impact_by_ticker" and "lookback_days" not in (args or {}):
            args = {**(args or {}), "lookback_days": lookback_days}
        return await run_tool_with_events(session, name, args or {}, emit_tool_start, emit_tool_end)

    user = _build_agent_user(question, intent, lookback_days)

    if not settings.anthropic_api_key:
        brief = await _deterministic_brief(session, intent, lookback_days, emit_tool_start, emit_tool_end)
        return brief, 0, 0

    try:
        parsed, _tool_log, in_t, out_t = await complete_json_with_tools_and_usage(
            REGULATIONS_AGENT_SYSTEM,
            user,
            ASK_REG_TOOLS,
            execute_tool_async=tool_dispatch,
            max_iters=5,
            max_tokens=4096,
        )
        return parsed, in_t, out_t
    except ValueError as e:
        if "JSON object" not in str(e):
            raise
        brief = await _deterministic_brief(session, intent, lookback_days, emit_tool_start, emit_tool_end)
        gaps = list(brief.get("gaps") or [])
        gaps.append("LLM research brief parse failed — used deterministic tool results.")
        brief["gaps"] = gaps
        return brief, 0, 0


def _build_agent_user(question: str, intent: dict[str, Any], lookback_days: int) -> str:
    extra = ""
    if intent.get("regulation_id"):
        extra = (
            f"\nThe user navigated from regulation id {intent['regulation_id']}. "
            "Call get_regulation with that document_id first.\n"
        )
    return (
        f"User question:\n{question.strip()}\n\n"
        f"Parsed intent (orchestrator):\n{json.dumps(intent, indent=2)}\n\n"
        f"Default lookback_days for impact_by_ticker: {lookback_days}\n"
        f"{extra}"
    )


def _trim_tool_output(output: dict[str, Any]) -> dict[str, Any]:
    """Keep SSE payloads UI-friendly."""
    text = json.dumps(output, default=str)
    if len(text) <= 4000:
        return output
    return {"note": "output truncated for stream", "preview": text[:3500] + "…"}


async def _deterministic_brief(
    session: AsyncSession,
    intent: dict[str, Any],
    lookback_days: int,
    emit_tool_start: Any,
    emit_tool_end: Any,
) -> dict[str, Any]:
    """No API key: run obvious tools without an LLM research step."""
    tickers = intent.get("tickers") or []
    topics = intent.get("topics") or []
    reg_id = intent.get("regulation_id")
    key_documents: list[dict[str, Any]] = []

    if reg_id:
        focused = await run_tool_with_events(
            session,
            "get_regulation",
            {"document_id": str(reg_id)},
            emit_tool_start,
            emit_tool_end,
        )
        if focused.get("found"):
            key_documents.append(
                {
                    "id": focused.get("id"),
                    "document_number": focused.get("document_number"),
                    "title": focused.get("title"),
                    "why_relevant": "User opened Ask from this regulation",
                }
            )
            for tk in focused.get("stock_link_tickers") or []:
                if tk and tk not in tickers:
                    tickers = [*tickers, str(tk).upper()]

    if tickers:
        t = str(tickers[0]).upper()
        await run_tool_with_events(
            session,
            "lookup_company_profile",
            {"ticker": t},
            emit_tool_start,
            emit_tool_end,
        )
        impact = await run_tool_with_events(
            session,
            "impact_by_ticker",
            {"ticker": t, "lookback_days": lookback_days},
            emit_tool_start,
            emit_tool_end,
        )
        for m in (impact.get("matches") or [])[:5]:
            key_documents.append(
                {
                    "id": m.get("id"),
                    "document_number": m.get("document_number"),
                    "title": m.get("title"),
                    "why_relevant": "Profile overlap (no LLM — deterministic run)",
                }
            )

    query = " ".join(topics) if topics else "regulation"
    search = await run_tool_with_events(
        session,
        "list_regulations",
        {"search": query, "limit": 5},
        emit_tool_start,
        emit_tool_end,
    )
    for m in (search.get("matches") or [])[:3]:
        if not any(k.get("id") == m.get("id") for k in key_documents):
            key_documents.append(
                {
                    "id": m.get("id"),
                    "document_number": m.get("document_number"),
                    "title": m.get("title"),
                    "why_relevant": f"Keyword search: {query}",
                }
            )

    return {
        "research_summary": (
            "Deterministic regulations scan (ANTHROPIC_API_KEY not set). "
            "Configure the API key for richer synthesis."
        ),
        "key_documents": key_documents,
        "tickers": tickers,
        "topics": topics,
        "gaps": ["LLM research and synthesis unavailable without ANTHROPIC_API_KEY"],
    }
