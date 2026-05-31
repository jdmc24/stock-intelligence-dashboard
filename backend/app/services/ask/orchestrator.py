from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.ask_prompts import SYNTHESIS_SYSTEM
from app.services.ask.events import AskEventEmitter
from app.services.ask.regulations_agent import run_regulations_agent
from app.services.llm.anthropic_client import complete_json_with_usage
from app.settings import settings

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]

_EARNINGS_HINTS = (
    "earnings",
    "earnings call",
    "conference call",
    "transcript",
    "on the call",
    "next call",
    "said on",
    "talk about on",
    "how will they",
    "how might they",
    "ceo",
    "cfo",
    "guidance",
    "prepared remarks",
)

_TICKER_STOP = frozenset(
    {
        "A",
        "I",
        "AI",
        "AN",
        "AND",
        "ARE",
        "FOR",
        "HOW",
        "ITS",
        "LLC",
        "NEW",
        "NOT",
        "SEC",
        "THE",
        "THIS",
        "THAT",
        "WHAT",
        "WHEN",
        "WHO",
        "WHY",
        "WILL",
        "WITH",
        "FROM",
        "THAN",
        "THAT",
        "THEY",
        "THEM",
        "US",
        "UK",
        "EU",
        "FR",
        "IT",
        "OR",
        "ON",
        "IN",
        "AT",
        "TO",
        "OF",
        "BY",
        "AS",
        "IF",
        "BE",
        "IS",
        "AM",
        "PM",
    }
)


def parse_intent(question: str, context: dict[str, Any] | None) -> dict[str, Any]:
    ctx = context or {}
    q = (question or "").strip()
    q_lower = q.lower()

    tickers: list[str] = []
    if ctx.get("ticker"):
        tickers.append(str(ctx["ticker"]).strip().upper())

    for m in re.finditer(r"\b([A-Z]{2,5})\b", q):
        sym = m.group(1).upper()
        if sym not in _TICKER_STOP and sym not in tickers:
            tickers.append(sym)

    needs_earnings = any(h in q_lower for h in _EARNINGS_HINTS)

    topics: list[str] = []
    for kw in ("artificial intelligence", "machine learning", "cybersecurity", "capital", "disclosure", "privacy"):
        if kw in q_lower:
            topics.append(kw)
    if " ai " in f" {q_lower} " or q_lower.startswith("ai ") or q_lower.endswith(" ai"):
        if "artificial intelligence" not in topics:
            topics.append("AI")

    if not topics and q:
        topics = [w for w in re.findall(r"[a-zA-Z]{4,}", q_lower) if w not in ("might", "would", "could", "about", "recent")][:3]

    return {
        "tickers": tickers[:3],
        "topics": topics[:5],
        "needs_earnings": needs_earnings,
        "regulation_id": ctx.get("regulation_id"),
    }


def build_plan(intent: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [
        {"id": "parse", "agent": "orchestrator", "label": "Understand your question", "status": "done"},
        {
            "id": "regulations",
            "agent": "regulations",
            "label": "Research relevant Federal Register rules",
            "status": "pending",
        },
    ]
    if intent.get("needs_earnings"):
        steps.append(
            {
                "id": "earnings",
                "agent": "earnings",
                "label": "Review earnings call narrative (coming soon)",
                "status": "skipped",
            }
        )
    steps.append(
        {"id": "synthesize", "agent": "synthesizer", "label": "Write your answer", "status": "pending"}
    )
    return {"intent": intent, "steps": steps}


async def run_ask(
    session: AsyncSession,
    *,
    question: str,
    context: dict[str, Any] | None,
    lookback_days: int,
    emitter: AskEventEmitter,
    emit: EventCallback,
) -> None:
    q = (question or "").strip()
    if not q:
        await emit(emitter.next("error", code="EMPTY_QUESTION", message="Question is required.", recoverable=True))
        await emit(emitter.next("run_end", status="error"))
        return

    await emit(
        emitter.next(
            "run_started",
            question=q,
            phase="regulations_only",
        )
    )

    intent = parse_intent(q, context)
    plan = build_plan(intent)
    await emit(emitter.next("plan", **plan))

    if intent.get("needs_earnings"):
        await emit(
            emitter.next(
                "message",
                level="warn",
                text=(
                    "Your question mentions earnings calls. Phase 1 covers regulations only — "
                    "earnings analysis will plug in here without changing the chat UI."
                ),
            )
        )

    await emit(emitter.next("agent_start", agent="orchestrator", label="Planning"))
    await emit(emitter.next("agent_end", agent="orchestrator", status="ok", summary="Plan ready"))

    await emit(emitter.next("agent_start", agent="regulations", label="Regulations research"))
    brief, in_reg, out_reg = await run_regulations_agent(
        session,
        question=q,
        intent=intent,
        lookback_days=lookback_days,
        emit=emit,
        emitter=emitter,
    )
    await emit(
        emitter.next(
            "agent_end",
            agent="regulations",
            status="ok",
            summary=(brief.get("research_summary") or "Regulations research complete.")[:240],
        )
    )

    await emit(emitter.next("agent_start", agent="synthesizer", label="Writing answer"))
    answer_payload, in_syn, out_syn = await _synthesize(q, intent, brief)
    limitations = list(answer_payload.get("limitations") or [])
    if intent.get("needs_earnings"):
        limitations.append("Earnings call analysis is not enabled yet (regulations-only phase).")
    answer_payload["limitations"] = limitations
    answer_payload["agents_used"] = ["orchestrator", "regulations", "synthesizer"]

    await emit(emitter.next("answer", **{k: v for k, v in answer_payload.items() if k != "type"}))
    await emit(emitter.next("agent_end", agent="synthesizer", status="ok"))

    status = "partial" if intent.get("needs_earnings") else "ok"
    await emit(
        emitter.next(
            "run_end",
            status=status,
            input_tokens=in_reg + in_syn,
            output_tokens=out_reg + out_syn,
        )
    )


async def _synthesize(question: str, intent: dict[str, Any], brief: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    if not settings.anthropic_api_key:
        md = _fallback_markdown(question, intent, brief)
        citations = _citations_from_brief(brief)
        return {"markdown": md, "citations": citations, "limitations": brief.get("gaps") or []}, 0, 0

    user = (
        f"User question:\n{question}\n\n"
        f"Intent:\n{json.dumps(intent, indent=2)}\n\n"
        f"Regulations research brief:\n{json.dumps(brief, indent=2, default=str)}\n"
    )
    parsed, in_t, out_t = await complete_json_with_usage(SYNTHESIS_SYSTEM, user, max_tokens=4096)
    citations = parsed.get("citations") if isinstance(parsed.get("citations"), list) else _citations_from_brief(brief)
    return {
        "markdown": str(parsed.get("markdown") or ""),
        "citations": citations,
        "limitations": parsed.get("limitations") if isinstance(parsed.get("limitations"), list) else [],
    }, in_t, out_t


def _citations_from_brief(brief: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in brief.get("key_documents") or []:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        if not doc_id:
            continue
        title = str(doc.get("title") or doc.get("document_number") or "Regulation")[:120]
        out.append(
            {
                "kind": "regulation",
                "id": str(doc_id),
                "label": title,
                "href": f"/regulations/{doc_id}",
            }
        )
    for t in brief.get("tickers") or []:
        tk = str(t).upper()
        out.append(
            {
                "kind": "company_profile",
                "id": tk,
                "label": tk,
                "href": f"/company/{tk}",
            }
        )
    return out


def _fallback_markdown(question: str, intent: dict[str, Any], brief: dict[str, Any]) -> str:
    lines = [
        f"**Question:** {question}",
        "",
        brief.get("research_summary") or "_No summary available._",
        "",
        "**Relevant documents**",
    ]
    docs = brief.get("key_documents") or []
    if not docs:
        lines.append("- None found in the lookback window. Try ingesting/enriching regulations or seeding company profiles.")
    else:
        for d in docs:
            title = d.get("title") or d.get("document_number") or "Document"
            doc_id = d.get("id")
            if doc_id:
                lines.append(f"- [{title}](/regulations/{doc_id})")
            else:
                lines.append(f"- {title}")
    lines.extend(
        [
            "",
            "_Informational only — not legal or compliance advice. Set ANTHROPIC_API_KEY for full AI synthesis._",
        ]
    )
    if intent.get("needs_earnings"):
        lines.append("")
        lines.append(
            "_Note: Earnings call analysis is planned for a later release; this answer is regulations-only._"
        )
    return "\n".join(lines)
