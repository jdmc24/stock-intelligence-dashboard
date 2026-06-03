from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_context
from app.prompts.ask_prompts import SYNTHESIS_SYSTEM
from app.services.ask.earnings_agent import run_earnings_agent
from app.services.ask.events import AskEventEmitter
from app.services.ask.regulations_agent import run_regulations_agent
from app.services.company_profile_service import ensure_company_reg_profile
from app.services.ticker_resolution import extract_explicit_tickers, resolve_tickers_for_question
from app.services.transcript_fetch_service import (
    ASK_EARNINGS_STORED_TARGET,
    ask_prefetch_targets,
    ensure_transcripts_for_ticker,
)
from app.services.llm.anthropic_client import complete_json_with_usage
from app.services.regulations_service import get_document
from app.settings import settings

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]

_EARNINGS_HINTS = (
    "earnings",
    "earnings call",
    "earning call",
    "conference call",
    "transcript",
    "on the call",
    "next call",
    "most recent call",
    "latest call",
    "highlights",
    "highlight",
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
    "compare",
    "comparison",
    "versus",
    " vs ",
    "say about",
)

_REGULATION_HINTS = (
    "regulation",
    "regulatory",
    "federal register",
    "rule",
    "rules",
    "compliance",
    "sec ",
    " sec",
    "occ ",
    "fdic",
    "cfpb",
    "frb",
    "fed ",
    "federal reserve",
    "dodd-frank",
    "basel",
    "capital requirement",
    "privacy rule",
    "disclosure requirement",
    "enforcement",
    "rulemaking",
    "proposed rule",
)


def parse_intent(question: str, context: dict[str, Any] | None) -> dict[str, Any]:
    ctx = context or {}
    q = (question or "").strip()
    q_lower = q.lower()

    tickers: list[str] = []
    if ctx.get("ticker"):
        tickers.append(str(ctx["ticker"]).strip().upper())

    tickers.extend(extract_explicit_tickers(q, tickers))
    # Preserve order while deduplicating.
    seen: set[str] = set()
    unique: list[str] = []
    for sym in tickers:
        up = sym.strip().upper()
        if not up or up in seen:
            continue
        seen.add(up)
        unique.append(up)
    tickers = unique[:5]

    needs_earnings = any(h in q_lower for h in _EARNINGS_HINTS)

    topics: list[str] = []
    for kw in ("artificial intelligence", "machine learning", "cybersecurity", "capital", "disclosure", "privacy"):
        if kw in q_lower:
            topics.append(kw)
    if " ai " in f" {q_lower} " or q_lower.startswith("ai ") or q_lower.endswith(" ai"):
        if "artificial intelligence" not in topics:
            topics.append("AI")

    if not topics and q:
        topics = [
            w
            for w in re.findall(r"[a-zA-Z]{4,}", q_lower)
            if w not in ("might", "would", "could", "about", "recent", "were", "most", "from", "what", "when")
        ][:3]

    needs_earnings = needs_earnings or (
        bool(tickers)
        and any(
            w in q_lower
            for w in (" call", "call ", "earning", "earnings", "transcript", "highlights", "guidance", "quarter")
        )
    )

    return {
        "tickers": tickers[:5],
        "topics": topics[:5],
        "needs_earnings": needs_earnings,
        "regulation_id": ctx.get("regulation_id"),
    }


def should_run_earnings(intent: dict[str, Any]) -> bool:
    """Run the earnings specialist when the question is about calls/transcripts."""
    if intent.get("needs_earnings"):
        return True
    tickers = intent.get("tickers") or []
    if not tickers:
        return False
    topics = [str(t).lower() for t in (intent.get("topics") or [])]
    call_topics = {"call", "calls", "earnings", "earning", "transcript", "highlights", "highlight", "guidance", "quarter"}
    return bool(call_topics.intersection(topics))


def should_run_regulations(question: str, intent: dict[str, Any]) -> bool:
    """Skip regulations research for earnings-only questions (saves a full agent loop)."""
    if intent.get("regulation_id"):
        return True
    q = (question or "").lower()
    if any(h in q for h in _REGULATION_HINTS):
        return True
    if "how might" in q and any(h in q for h in ("rule", "regulation", "regulatory", "compliance", "law")):
        return True
    if intent.get("needs_earnings") and not any(h in q for h in _REGULATION_HINTS):
        return False
    return True


def build_plan(intent: dict[str, Any], *, run_regulations: bool = True) -> dict[str, Any]:
    run_earnings = should_run_earnings(intent)
    steps: list[dict[str, Any]] = [
        {"id": "parse", "agent": "orchestrator", "label": "Understand your question", "status": "done"},
    ]
    if run_regulations:
        steps.append(
            {
                "id": "regulations",
                "agent": "regulations",
                "label": "Research relevant Federal Register rules",
                "status": "pending",
            }
        )
    else:
        steps.append(
            {
                "id": "regulations",
                "agent": "regulations",
                "label": "Research relevant Federal Register rules",
                "status": "skipped",
            }
        )
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

    resolved_tickers, ticker_notes = await resolve_tickers_for_question(
        session,
        q,
        intent.get("tickers"),
    )
    intent["tickers"] = resolved_tickers

    run_earnings = should_run_earnings(intent)
    run_regulations = should_run_regulations(q, intent)

    await emit(
        emitter.next(
            "run_started",
            question=q,
            phase=(
                "regulations_and_earnings"
                if run_earnings and run_regulations
                else "earnings_only"
                if run_earnings
                else "regulations_only"
            ),
        )
    )

    for note in ticker_notes:
        await emit(emitter.next("message", level="info", text=note))

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

    plan = build_plan(intent, run_regulations=run_regulations)
    await emit(emitter.next("plan", **plan))

    await emit(emitter.next("agent_start", agent="orchestrator", label="Planning"))

    profile_tasks = [
        ensure_company_reg_profile(session, str(tk), context_question=q)
        for tk in (intent.get("tickers") or [])
    ]
    if profile_tasks:
        profile_results = await asyncio.gather(*profile_tasks)
        for (profile, created), tk in zip(profile_results, intent.get("tickers") or []):
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

    async def _prefetch_one(
        tk: str,
        min_count: int,
        max_fetch: int,
        *,
        run_analysis: bool,
    ) -> tuple[str, list, list[str]]:
        t_up = str(tk).strip().upper()
        async with session_context() as iso_session:
            transcripts, fetch_notes = await ensure_transcripts_for_ticker(
                iso_session,
                t_up,
                min_count=min_count,
                max_fetch=max_fetch,
                run_analysis=run_analysis,
            )
        return t_up, transcripts, fetch_notes

    if run_earnings:
        ticker_list = [str(tk) for tk in (intent.get("tickers") or [])]
        min_count, max_fetch, run_analysis = ask_prefetch_targets(q, ticker_count=len(ticker_list))
        prefetch_notes: list[str] = []
        prefetched: set[str] = set()

        if len(ticker_list) >= 2 and any(
            h in q.lower() for h in ("compare", "comparison", "versus", " vs ", " vs.")
        ):
            await emit(
                emitter.next(
                    "message",
                    level="info",
                    text=(
                        "Compare mode: fetching a few recent calls per ticker in parallel "
                        "(skipping heavy analysis during prefetch for speed)."
                    ),
                )
            )

        if ticker_list:
            prefetch_results = await asyncio.gather(
                *[
                    _prefetch_one(tk, min_count, max_fetch, run_analysis=run_analysis)
                    for tk in ticker_list
                ]
            )
            for t_up, transcripts, fetch_notes in prefetch_results:
                if not t_up:
                    continue
                prefetched.add(t_up)
                prefetch_notes.extend(fetch_notes)
                coverage = intent.setdefault("earnings_coverage", {})
                coverage[t_up] = {
                    "stored": len(transcripts),
                    "target_this_run": min_count,
                    "stored_goal": ASK_EARNINGS_STORED_TARGET,
                    "newest_quarter": transcripts[0].quarter if transcripts else None,
                }
                for note in fetch_notes:
                    level = "warn" if note.startswith("Could not fetch") or note.startswith("No earnings") else "info"
                    await emit(emitter.next("message", level=level, text=note))

        if run_earnings and not intent.get("tickers"):
            prefetch_notes.append(
                "No ticker resolved from the company name — transcript prefetch was skipped. "
                "Try including the ticker symbol (e.g. COST) or a clearer company name."
            )
            await emit(emitter.next("message", level="warn", text=prefetch_notes[-1]))
        intent["prefetch_notes"] = prefetch_notes
        intent["_prefetched_tickers"] = sorted(prefetched)

    await emit(emitter.next("agent_end", agent="orchestrator", status="ok", summary="Plan ready"))

    in_reg = out_reg = in_ear = out_ear = 0
    reg_brief: dict[str, Any] = {
        "research_summary": "Regulations research skipped for this earnings-focused question.",
        "key_documents": [],
        "tickers": list(intent.get("tickers") or []),
        "topics": intent.get("topics") or [],
        "gaps": [],
    }
    earn_brief: dict[str, Any] | None = None

    if run_regulations:
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
    else:
        await emit(
            emitter.next(
                "message",
                level="info",
                text="Skipping regulations research — earnings-only question.",
            )
        )

    if run_earnings:
        merged_tickers = list(intent.get("tickers") or [])
        seen_tickers = set(str(t).upper() for t in merged_tickers)
        for tk in reg_brief.get("tickers") or []:
            t_up = str(tk or "").strip().upper()
            if t_up and t_up not in seen_tickers:
                seen_tickers.add(t_up)
                merged_tickers.append(t_up)
        new_for_prefetch = [
            t
            for t in merged_tickers
            if t not in set(intent.get("_prefetched_tickers") or [])
        ]
        if new_for_prefetch:
            min_count, max_fetch, run_analysis = ask_prefetch_targets(q, ticker_count=len(new_for_prefetch))
            late_results = await asyncio.gather(
                *[
                    _prefetch_one(tk, min_count, max_fetch, run_analysis=run_analysis)
                    for tk in new_for_prefetch
                ]
            )
            for t_up, transcripts, fetch_notes in late_results:
                intent.setdefault("prefetch_notes", []).extend(fetch_notes)
                coverage = intent.setdefault("earnings_coverage", {})
                coverage[t_up] = {
                    "stored": len(transcripts),
                    "target_this_run": min_count,
                    "stored_goal": ASK_EARNINGS_STORED_TARGET,
                    "newest_quarter": transcripts[0].quarter if transcripts else None,
                }
                for note in fetch_notes:
                    level = "warn" if note.startswith("Could not fetch") or note.startswith("No earnings") else "info"
                    await emit(emitter.next("message", level=level, text=note))
                prefetched = set(intent.get("_prefetched_tickers") or [])
                prefetched.add(t_up)
                intent["_prefetched_tickers"] = sorted(prefetched)
            intent["tickers"] = merged_tickers[:5]
            for tk in new_for_prefetch:
                await emit(
                    emitter.next(
                        "message",
                        level="info",
                        text=f"Late prefetch for {tk} after regulations agent resolved ticker.",
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

    agents_used = ["orchestrator", "synthesizer"]
    if run_regulations:
        agents_used.insert(1, "regulations")
    if run_earnings:
        agents_used.insert(-1, "earnings")
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
        for note in intent.get("prefetch_notes") or []:
            if note.startswith("Could not fetch") or note.startswith("No earnings") or "skipped" in note.lower():
                limitations.append(note)
        limitations.extend(_earnings_scope_limitations(intent, earn_brief))
        return {
            "markdown": md,
            "citations": citations,
            "limitations": limitations,
            "follow_up_questions": suggest_follow_up_questions(question, intent, reg_brief, earn_brief),
        }, 0, 0

    user_parts = [
        f"User question:\n{question}\n",
        f"Intent:\n{json.dumps(intent, indent=2)}\n",
        f"Regulations research brief:\n{json.dumps(_compact_brief(reg_brief), indent=2, default=str)}\n",
    ]
    if earn_brief:
        user_parts.append(
            f"Earnings research brief:\n{json.dumps(_compact_brief(earn_brief), indent=2, default=str)}\n"
        )
    else:
        user_parts.append("Earnings research brief: not collected for this question.\n")
    user = "\n".join(user_parts)

    try:
        parsed, in_t, out_t = await asyncio.to_thread(
            complete_json_with_usage,
            SYNTHESIS_SYSTEM,
            user,
            8192,
        )
    except ValueError as e:
        if "JSON object" not in str(e):
            raise
        md = _fallback_markdown(question, intent, reg_brief, earn_brief)
        citations = _citations_from_briefs(reg_brief, earn_brief)
        limitations = list(reg_brief.get("gaps") or [])
        if earn_brief:
            limitations.extend(earn_brief.get("gaps") or [])
        for note in intent.get("prefetch_notes") or []:
            if note.startswith("Could not fetch") or note.startswith("No earnings") or "skipped" in note.lower():
                limitations.append(note)
        limitations.extend(_earnings_scope_limitations(intent, earn_brief))
        limitations.append("Answer synthesized from research briefs after JSON parse failure.")
        return {
            "markdown": md,
            "citations": citations,
            "limitations": limitations,
            "follow_up_questions": suggest_follow_up_questions(question, intent, reg_brief, earn_brief),
        }, 0, 0

    citations = (
        parsed.get("citations")
        if isinstance(parsed.get("citations"), list)
        else _citations_from_briefs(reg_brief, earn_brief)
    )
    limitations = parsed.get("limitations") if isinstance(parsed.get("limitations"), list) else []
    for note in intent.get("prefetch_notes") or []:
        if note.startswith("Could not fetch") or note.startswith("No earnings") or "skipped" in note.lower():
            if note not in limitations:
                limitations.append(note)
    for scope_note in _earnings_scope_limitations(intent, earn_brief):
        if scope_note not in limitations:
            limitations.append(scope_note)
    follow_ups = _normalize_follow_up_questions(parsed.get("follow_up_questions"))
    if not follow_ups:
        follow_ups = suggest_follow_up_questions(question, intent, reg_brief, earn_brief)
    return {
        "markdown": str(parsed.get("markdown") or ""),
        "citations": citations,
        "limitations": limitations,
        "follow_up_questions": follow_ups,
    }, in_t, out_t


def _earnings_scope_limitations(intent: dict[str, Any], earn_brief: dict[str, Any] | None) -> list[str]:
    """User-friendly scope notes when earnings coverage is thin — not dead ends."""
    if not earn_brief and not intent.get("needs_earnings"):
        return []
    coverage = intent.get("earnings_coverage")
    if not isinstance(coverage, dict) or not coverage:
        return []

    out: list[str] = []
    for ticker, info in coverage.items():
        if not isinstance(info, dict):
            continue
        t_up = str(ticker).strip().upper()
        stored = int(info.get("stored") or 0)
        goal = int(info.get("stored_goal") or ASK_EARNINGS_STORED_TARGET)
        newest = info.get("newest_quarter")
        if stored <= 0:
            continue
        q_part = f" ({newest})" if newest else ""
        if stored == 1:
            out.append(
                f"This answer is based on one earnings call{q_part} for {t_up}. "
                f"Ask can load up to {goal} recent quarters — try asking how a topic evolved over the last several calls."
            )
        elif stored < goal:
            out.append(
                f"Earnings context for {t_up} uses {stored} stored call(s) so far "
                f"(up to {goal} can be loaded with continued Ask questions)."
            )
    return out


def _normalize_follow_up_questions(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        q = item.strip()
        key = q.lower()
        if len(q) < 12 or key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= 3:
            break
    return out


def suggest_follow_up_questions(
    question: str,
    intent: dict[str, Any],
    reg_brief: dict[str, Any],
    earn_brief: dict[str, Any] | None,
) -> list[str]:
    """Deterministic follow-ups when the synthesizer omits them."""
    tickers: list[str] = []
    seen: set[str] = set()
    for source in (intent.get("tickers") or [], reg_brief.get("tickers") or []):
        for tk in source:
            t = str(tk or "").strip().upper()
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
    if earn_brief:
        for tk in earn_brief.get("tickers") or []:
            t = str(tk or "").strip().upper()
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)

    primary = tickers[0] if tickers else None
    coverage = intent.get("earnings_coverage") if isinstance(intent.get("earnings_coverage"), dict) else {}
    primary_stored = 0
    if primary and primary in coverage and isinstance(coverage[primary], dict):
        primary_stored = int(coverage[primary].get("stored") or 0)

    topics = [str(t) for t in (intent.get("topics") or reg_brief.get("topics") or []) if str(t).strip()]
    topic = topics[0] if topics else "AI"
    q_lower = (question or "").lower()
    had_earnings = bool(intent.get("needs_earnings") or earn_brief)
    had_regs = bool(reg_brief.get("key_documents"))

    suggestions: list[str] = []
    if primary and had_earnings and primary_stored <= 2:
        suggestions.append(
            f"How has {primary}'s tone and guidance changed over the last several earnings calls?"
        )
    elif primary and had_earnings and "ai" not in q_lower and topic.lower() != "ai":
        suggestions.append(
            f"What did management say about AI on {primary}'s most recent earnings call?"
        )
    elif primary and had_earnings:
        suggestions.append(
            f"How has {primary}'s guidance and tone changed over the last few earnings calls?"
        )

    if primary and had_regs:
        suggestions.append(
            f"What recent regulations are relevant for an investor considering {primary}?"
        )
    elif primary:
        suggestions.append(
            f"What Federal Register rules from the last 90 days might affect {primary}?"
        )

    if primary and had_earnings and had_regs and len(suggestions) < 3:
        suggestions.append(
            f"How might recent banking regulations intersect with themes {primary} raised on its latest call?"
        )
    elif primary and len(suggestions) < 3:
        suggestions.append(f"Compare {primary}'s latest earnings narrative to its regulatory exposure profile.")

    out: list[str] = []
    seen_q: set[str] = set()
    for s in suggestions:
        key = s.lower()
        if key in seen_q or key == q_lower.strip():
            continue
        seen_q.add(key)
        out.append(s)
        if len(out) >= 3:
            break
    return out


def _compact_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Keep synthesizer prompts bounded so the model has room for JSON output."""
    if not brief:
        return {}
    compact = {
        "research_summary": brief.get("research_summary"),
        "tickers": brief.get("tickers"),
        "topics": brief.get("topics"),
        "gaps": brief.get("gaps"),
        "narrative_themes": brief.get("narrative_themes"),
    }
    if brief.get("key_documents") is not None:
        compact["key_documents"] = (brief.get("key_documents") or [])[:6]
    if brief.get("key_transcripts") is not None:
        compact["key_transcripts"] = (brief.get("key_transcripts") or [])[:4]
    if brief.get("notable_quotes") is not None:
        compact["notable_quotes"] = (brief.get("notable_quotes") or [])[:6]
    if brief.get("timeline_point_count") is not None:
        compact["timeline_point_count"] = brief.get("timeline_point_count")
    return compact


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
