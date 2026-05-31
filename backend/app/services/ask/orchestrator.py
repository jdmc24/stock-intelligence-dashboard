from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.ask_prompts import SYNTHESIS_SYSTEM
from app.services.ask.earnings_agent import run_earnings_agent
from app.services.ask.events import AskEventEmitter
from app.services.ask.regulations_agent import run_regulations_agent
from app.services.company_profile_service import ensure_company_reg_profile
from app.services.transcript_fetch_service import ensure_transcripts_for_ticker
from app.services.llm.anthropic_client import complete_json_with_usage
from app.services.regulations_service import get_document
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
    "talks about",
    "talk about",
    "how will they",
    "how might they",
    "discuss",
    "discusses",
    "narrative",
    "commentary",
    "ceo",
    "cfo",
    "guidance",
    "prepared remarks",
    "mention on the call",
    "say about",
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


def should_run_earnings(intent: dict[str, Any]) -> bool:
    if intent.get("needs_earnings"):
        return True
    tickers = intent.get("tickers") or []
    topics = intent.get("topics") or []
    return bool(tickers and topics)


def build_plan(intent: dict[str, Any]) -> dict[str, Any]:
    run_earnings = should_run_earnings(intent)
    steps: list[dict[str, Any]] = [
        {"id": "parse", "agent": "orchestrator", "label": "Understand your question", "status": "done"},
        {
            "id": "regulations",
            "agent": "regulations",
            "label": "Research relevant Federal Register rules",
            "status": "pending",
        },
    ]
    if run_earnings:
        steps.append(
            {
                "id": "earnings",
                "agent": "earnings",
                "label": "Review earnings call narrative",
                "status": "pending",
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

    intent = parse_intent(q, context)
    run_earnings = should_run_earnings(intent)

    await emit(
        emitter.next(
            "run_started",
            question=q,
            phase="regulations_and_earnings" if run_earnings else "regulations_only",
        )
    )

    if intent.get("regulation_id"):
        doc = await get_document(session, str(intent["regulation_id"]))
        if doc:
            await emit(
                emitter.next(
                    "message",
                    level="info",
                    text=f"Focused on regulation {doc.get('document_number') or doc.get('id')}.",
                )
            )
            tickers = list(intent.get("tickers") or [])
            for sl in doc.get("stock_links") or []:
                tk = str(sl.get("ticker") or "").strip().upper()
                if tk and tk not in tickers:
                    tickers.append(tk)
            intent["tickers"] = tickers[:5]
            if tickers and (intent.get("topics") or intent.get("needs_earnings")):
                run_earnings = should_run_earnings(intent)

    plan = build_plan(intent)
    await emit(emitter.next("plan", **plan))

    await emit(emitter.next("agent_start", agent="orchestrator", label="Planning"))

    for tk in intent.get("tickers") or []:
        profile, created = await ensure_company_reg_profile(session, str(tk), context_question=q)
        if created and profile:
            await emit(
                emitter.next(
                    "message",
                    level="info",
                    text=(
                        f"Auto-created regulatory profile for {profile.ticker} ({profile.name}). "
                        "Tags are inferred — refine on the company page if needed."
                    ),
                )
            )

    if run_earnings:
        for tk in intent.get("tickers") or []:
            _transcripts, fetch_notes = await ensure_transcripts_for_ticker(
                session,
                str(tk),
                min_count=1,
                run_analysis=True,
            )
            for note in fetch_notes:
                level = "warn" if note.startswith("Could not fetch") else "info"
                await emit(emitter.next("message", level=level, text=note))

    await emit(emitter.next("agent_end", agent="orchestrator", status="ok", summary="Plan ready"))

    in_reg = out_reg = in_ear = out_ear = 0
    reg_brief: dict[str, Any]
    earn_brief: dict[str, Any] | None = None

    await emit(emitter.next("agent_start", agent="regulations", label="Regulations research"))
    reg_brief, in_reg, out_reg = await run_regulations_agent(
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
            summary=(reg_brief.get("research_summary") or "Regulations research complete.")[:240],
        )
    )

    if run_earnings:
        await emit(emitter.next("agent_start", agent="earnings", label="Earnings research"))
        earn_brief, in_ear, out_ear = await run_earnings_agent(
            session,
            question=q,
            intent=intent,
            emit=emit,
            emitter=emitter,
        )
        await emit(
            emitter.next(
                "agent_end",
                agent="earnings",
                status="ok",
                summary=(earn_brief.get("research_summary") or "Earnings research complete.")[:240],
            )
        )

    await emit(emitter.next("agent_start", agent="synthesizer", label="Writing answer"))
    answer_payload, in_syn, out_syn = await _synthesize(q, intent, reg_brief, earn_brief)

    agents_used = ["orchestrator", "regulations", "synthesizer"]
    if run_earnings:
        agents_used.insert(2, "earnings")
    answer_payload["agents_used"] = agents_used

    await emit(emitter.next("answer", **{k: v for k, v in answer_payload.items() if k != "type"}))
    await emit(emitter.next("agent_end", agent="synthesizer", status="ok"))

    status = "ok"
    if run_earnings and earn_brief:
        gaps = earn_brief.get("gaps") or []
        if gaps or not (earn_brief.get("key_transcripts") or earn_brief.get("notable_quotes")):
            status = "partial"

    await emit(
        emitter.next(
            "run_end",
            status=status,
            input_tokens=in_reg + in_ear + in_syn,
            output_tokens=out_reg + out_ear + out_syn,
        )
    )


async def _synthesize(
    question: str,
    intent: dict[str, Any],
    reg_brief: dict[str, Any],
    earn_brief: dict[str, Any] | None,
) -> tuple[dict[str, Any], int, int]:
    if not settings.anthropic_api_key:
        md = _fallback_markdown(question, intent, reg_brief, earn_brief)
        citations = _citations_from_briefs(reg_brief, earn_brief)
        limitations = list(reg_brief.get("gaps") or [])
        if earn_brief:
            limitations.extend(earn_brief.get("gaps") or [])
        return {"markdown": md, "citations": citations, "limitations": limitations}, 0, 0

    user_parts = [
        f"User question:\n{question}\n",
        f"Intent:\n{json.dumps(intent, indent=2)}\n",
        f"Regulations research brief:\n{json.dumps(reg_brief, indent=2, default=str)}\n",
    ]
    if earn_brief:
        user_parts.append(f"Earnings research brief:\n{json.dumps(earn_brief, indent=2, default=str)}\n")
    else:
        user_parts.append("Earnings research brief: not collected for this question.\n")
    user = "\n".join(user_parts)

    parsed, in_t, out_t = await asyncio.to_thread(
        complete_json_with_usage,
        SYNTHESIS_SYSTEM,
        user,
        4096,
    )
    citations = (
        parsed.get("citations")
        if isinstance(parsed.get("citations"), list)
        else _citations_from_briefs(reg_brief, earn_brief)
    )
    return {
        "markdown": str(parsed.get("markdown") or ""),
        "citations": citations,
        "limitations": parsed.get("limitations") if isinstance(parsed.get("limitations"), list) else [],
    }, in_t, out_t


def _citations_from_briefs(reg_brief: dict[str, Any], earn_brief: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, item_id: str, label: str, href: str) -> None:
        key = (kind, item_id)
        if key in seen:
            return
        seen.add(key)
        out.append({"kind": kind, "id": item_id, "label": label, "href": href})

    for doc in reg_brief.get("key_documents") or []:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        if not doc_id:
            continue
        title = str(doc.get("title") or doc.get("document_number") or "Regulation")[:120]
        add("regulation", str(doc_id), title, f"/regulations/{doc_id}")

    tickers = set(str(t).upper() for t in (reg_brief.get("tickers") or []))
    if earn_brief:
        tickers.update(str(t).upper() for t in (earn_brief.get("tickers") or []))
    for tk in sorted(tickers):
        add("company_profile", tk, tk, f"/company/{tk}")

    if earn_brief:
        for tr in earn_brief.get("key_transcripts") or []:
            if not isinstance(tr, dict):
                continue
            tid = tr.get("transcript_id")
            if not tid:
                continue
            tk = str(tr.get("ticker") or "").upper()
            qtr = tr.get("quarter") or "call"
            label = f"{tk} {qtr}".strip()[:120]
            add("transcript", str(tid), label, f"/transcripts/{tid}")
            add("analysis", str(tid), f"{label} analysis", f"/analysis/{tid}")

    return out


def _fallback_markdown(
    question: str,
    intent: dict[str, Any],
    reg_brief: dict[str, Any],
    earn_brief: dict[str, Any] | None,
) -> str:
    lines = [
        f"**Question:** {question}",
        "",
        "**Regulations**",
        "",
        reg_brief.get("research_summary") or "_No summary available._",
        "",
        "**Relevant documents**",
    ]
    docs = reg_brief.get("key_documents") or []
    if not docs:
        lines.append("- None found in the lookback window.")
    else:
        for d in docs:
            title = d.get("title") or d.get("document_number") or "Document"
            doc_id = d.get("id")
            if doc_id:
                lines.append(f"- [{title}](/regulations/{doc_id})")
            else:
                lines.append(f"- {title}")

    if earn_brief:
        lines.extend(["", "**Earnings calls**", "", earn_brief.get("research_summary") or "_No earnings summary._"])
        transcripts = earn_brief.get("key_transcripts") or []
        if transcripts:
            lines.append("")
            lines.append("**Recent call themes**")
            for tr in transcripts:
                tid = tr.get("transcript_id")
                tk = tr.get("ticker") or ""
                qtr = tr.get("quarter") or ""
                label = f"{tk} {qtr}".strip()
                if tid:
                    lines.append(f"- [{label}](/analysis/{tid})")
                topics = tr.get("top_topics") or []
                if topics:
                    lines.append(f"  - Topics: {', '.join(str(t) for t in topics[:5])}")
        quotes = earn_brief.get("notable_quotes") or []
        if quotes:
            lines.append("")
            lines.append("**Notable quotes**")
            for q in quotes[:3]:
                speaker = q.get("speaker") or "Speaker"
                excerpt = q.get("excerpt") or ""
                lines.append(f'- {speaker}: "{excerpt}"')

    lines.extend(
        [
            "",
            "_Informational only — not legal or compliance advice. Set ANTHROPIC_API_KEY for full AI synthesis._",
        ]
    )
    return "\n".join(lines)
