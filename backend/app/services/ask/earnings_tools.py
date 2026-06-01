from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalysisResult, Transcript, TranscriptSection
from app.services.comparison_runner import quarter_sort_key

from app.services.ticker_resolution import LOOKUP_COMPANY_TICKER_TOOL, lookup_company_ticker

ASK_EARNINGS_TOOLS: list[dict[str, Any]] = [
    LOOKUP_COMPANY_TICKER_TOOL,
    {
        "name": "list_transcripts_for_ticker",
        "description": (
            "List stored earnings call transcripts for a ticker, newest first. "
            "The orchestrator pre-loads up to 16 recent quarters before you run; "
            "this tool only reads what is already in the database."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. MSFT."},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Max transcripts (default 5).",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_transcript_analysis",
        "description": (
            "Load AI analysis for one transcript (summary, sentiment, hedging, guidance, topics). "
            "Read-only — does not trigger new analysis jobs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transcript_id": {"type": "string", "description": "Transcript uuid from list or search tools."},
            },
            "required": ["transcript_id"],
        },
    },
    {
        "name": "search_transcript_quotes",
        "description": (
            "Find speaker sections whose text contains a phrase. "
            "Best for how executives talked about a topic on past calls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Phrase to search in section text."},
                "company": {
                    "type": "string",
                    "description": "Optional ticker filter.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_transcripts",
        "description": (
            "Search full transcript text by keyword and/or ticker. "
            "Returns snippets — use get_transcript_analysis for structured themes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Optional ticker filter."},
                "q": {"type": "string", "description": "Keyword in full transcript text."},
                "topic": {"type": "string", "description": "Alias for q — substring match."},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Max hits (default 8).",
                },
            },
        },
    },
    {
        "name": "company_earnings_timeline",
        "description": (
            "Summarize analyzed calls for a ticker over time: tone, hedging, guidance count, top topics per quarter."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker."},
            },
            "required": ["ticker"],
        },
    },
]


def _snippet(text: str, needle: str, radius: int = 90) -> str:
    if not text:
        return ""
    n = needle.strip().lower()
    if not n:
        tail = text[:220]
        return tail + ("…" if len(text) > 220 else "")
    low = text.lower()
    idx = low.find(n)
    if idx < 0:
        tail = text[:220]
        return tail + ("…" if len(text) > 220 else "")
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    out = text[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def _loads(s: str | None) -> dict[str, Any] | None:
    if not s:
        return None
    try:
        o = json.loads(s)
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        return None


async def _list_transcripts_for_ticker(
    session: AsyncSession,
    ticker: str,
    limit: int = 5,
) -> dict[str, Any]:
    t_up = (ticker or "").strip().upper()
    if not t_up:
        return {"found": False, "note": "empty ticker"}
    n = max(1, min(int(limit or 5), 20))
    res = await session.execute(
        select(Transcript)
        .where(func.upper(Transcript.ticker) == t_up)
        .order_by(Transcript.created_at.desc())
        .limit(n)
    )
    rows = list(res.scalars().all())
    if not rows:
        return {"found": False, "ticker": t_up, "note": "No transcripts stored for this ticker."}
    items = []
    for tr in rows:
        items.append(
            {
                "transcript_id": tr.id,
                "ticker": tr.ticker,
                "quarter": tr.quarter,
                "call_date": tr.call_date.isoformat() if tr.call_date else None,
                "company_name": tr.company_name,
                "status": tr.status,
            }
        )
    return {"found": True, "ticker": t_up, "count": len(items), "transcripts": items}


async def _get_transcript_analysis(session: AsyncSession, transcript_id: str) -> dict[str, Any]:
    tid = (transcript_id or "").strip()
    if not tid:
        return {"found": False, "note": "empty transcript_id"}
    tr = await session.get(Transcript, tid)
    if tr is None:
        return {"found": False, "transcript_id": tid, "note": "Transcript not found."}
    res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == tid))
    row = res.scalar_one_or_none()
    if row is None:
        return {
            "found": True,
            "transcript_id": tid,
            "ticker": tr.ticker,
            "quarter": tr.quarter,
            "status": "no_analysis",
            "note": "No analysis row — transcript may need analysis on the Earnings page.",
        }
    if row.status != "complete":
        return {
            "found": True,
            "transcript_id": tid,
            "ticker": tr.ticker,
            "quarter": tr.quarter,
            "status": row.status,
            "error_message": row.error_message,
        }
    sentiment = _loads(row.sentiment_json) or {}
    hedging = _loads(row.hedging_json) or {}
    guidance = _loads(row.guidance_json) or {}
    topics = _loads(row.topics_json) or {}
    topic_items = topics.get("topics") if isinstance(topics, dict) else None
    top_topics: list[dict[str, Any]] = []
    if isinstance(topic_items, list):
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in topic_items:
            if not isinstance(item, dict):
                continue
            rel = item.get("relevance")
            r = float(rel) if isinstance(rel, (int, float)) else 0.0
            scored.append((r, item))
        scored.sort(key=lambda x: -x[0])
        for _, item in scored[:6]:
            top_topics.append(
                {
                    "topic": item.get("topic"),
                    "relevance": item.get("relevance"),
                    "summary": (str(item.get("summary") or ""))[:300],
                }
            )
    glist = guidance.get("guidance") if isinstance(guidance, dict) else None
    guidance_preview: list[str] = []
    if isinstance(glist, list):
        for g in glist[:4]:
            if isinstance(g, dict) and g.get("statement"):
                guidance_preview.append(str(g["statement"])[:200])
            elif isinstance(g, str):
                guidance_preview.append(g[:200])
    return {
        "found": True,
        "transcript_id": tid,
        "ticker": tr.ticker,
        "quarter": tr.quarter,
        "call_date": tr.call_date.isoformat() if tr.call_date else None,
        "status": "complete",
        "summary": (row.summary or "")[:1200],
        "overall_tone": sentiment.get("overall_tone") if isinstance(sentiment, dict) else None,
        "hedging_score": hedging.get("hedging_score") if isinstance(hedging, dict) else None,
        "guidance_count": len(glist) if isinstance(glist, list) else 0,
        "guidance_preview": guidance_preview,
        "top_topics": top_topics,
    }


async def _search_transcript_quotes(
    session: AsyncSession,
    query: str,
    company: str | None = None,
) -> dict[str, Any]:
    qn = (query or "").strip()
    if len(qn) < 2:
        return {"found": False, "note": "query too short"}
    conds = [func.instr(func.lower(TranscriptSection.text), qn.lower()) > 0]
    if company and company.strip():
        conds.append(func.upper(Transcript.ticker) == company.strip().upper())
    stmt = (
        select(TranscriptSection, Transcript)
        .join(Transcript, TranscriptSection.transcript_id == Transcript.id)
        .where(*conds)
        .order_by(Transcript.created_at.desc(), TranscriptSection.order.asc())
        .limit(12)
    )
    res = await session.execute(stmt)
    pairs = list(res.all())
    quotes = []
    for sec, tr in pairs:
        quotes.append(
            {
                "transcript_id": tr.id,
                "ticker": tr.ticker,
                "quarter": tr.quarter,
                "section_type": sec.section_type,
                "speaker": sec.speaker,
                "excerpt": _snippet(sec.text, qn, radius=120),
            }
        )
    return {"found": bool(quotes), "query": qn, "count": len(quotes), "quotes": quotes}


async def _search_transcripts(
    session: AsyncSession,
    company: str | None = None,
    q: str | None = None,
    topic: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    c = company.strip() if company else None
    qq = (q or topic or "").strip()
    if not c and not qq:
        return {"found": False, "note": "Provide company and/or q/topic."}
    conds = []
    if c:
        conds.append(func.upper(Transcript.ticker) == c.upper())
    if qq:
        conds.append(func.instr(func.lower(Transcript.raw_text), qq.lower()) > 0)
    n = max(1, min(int(limit or 8), 20))
    stmt = select(Transcript).where(*conds).order_by(Transcript.created_at.desc()).limit(n)
    res = await session.execute(stmt)
    rows = list(res.scalars().all())
    hits = []
    for tr in rows:
        hits.append(
            {
                "transcript_id": tr.id,
                "ticker": tr.ticker,
                "quarter": tr.quarter,
                "status": tr.status,
                "snippet": _snippet(tr.raw_text, qq),
            }
        )
    return {"found": bool(hits), "count": len(hits), "hits": hits}


async def _company_earnings_timeline(session: AsyncSession, ticker: str) -> dict[str, Any]:
    t_up = (ticker or "").strip().upper()
    if not t_up:
        return {"found": False, "note": "empty ticker"}
    res = await session.execute(select(Transcript).where(func.upper(Transcript.ticker) == t_up))
    transcripts = list(res.scalars().all())
    if not transcripts:
        return {"found": False, "ticker": t_up, "note": "No transcripts for this ticker."}
    company_name = next((x.company_name for x in transcripts if x.company_name), None)
    ordered = sorted(transcripts, key=quarter_sort_key)
    points: list[dict[str, Any]] = []
    for t in ordered:
        if t.status != "analyzed":
            continue
        ar_res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == t.id))
        ar = ar_res.scalar_one_or_none()
        if ar is None or ar.status != "complete":
            continue
        sent = _loads(ar.sentiment_json) or {}
        hed = _loads(ar.hedging_json) or {}
        guid = _loads(ar.guidance_json) or {}
        top = _loads(ar.topics_json) or {}
        topic_names: list[str] = []
        topics_list = top.get("topics") if isinstance(top, dict) else None
        if isinstance(topics_list, list):
            scored: list[tuple[float, str]] = []
            for item in topics_list:
                if not isinstance(item, dict):
                    continue
                name = item.get("topic")
                if not isinstance(name, str):
                    continue
                rel = item.get("relevance")
                r = float(rel) if isinstance(rel, (int, float)) else 0.0
                scored.append((r, name))
            scored.sort(key=lambda x: -x[0])
            topic_names = [n for _, n in scored[:6]]
        glist = guid.get("guidance") if isinstance(guid, dict) else None
        points.append(
            {
                "transcript_id": t.id,
                "quarter": t.quarter,
                "call_date": t.call_date.isoformat() if t.call_date else None,
                "overall_tone": sent.get("overall_tone") if isinstance(sent, dict) else None,
                "hedging_score": hed.get("hedging_score") if isinstance(hed, dict) else None,
                "guidance_count": len(glist) if isinstance(glist, list) else 0,
                "top_topics": topic_names,
            }
        )
    return {
        "found": bool(points),
        "ticker": t_up,
        "company_name": company_name,
        "analyzed_call_count": len(points),
        "points": points,
    }


async def execute_ask_earnings_tool(session: AsyncSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    args = arguments or {}
    if name == "lookup_company_ticker":
        return await lookup_company_ticker(
            session,
            company_name=str(args.get("company_name") or ""),
            limit=int(args.get("limit") or 3),
        )
    if name == "list_transcripts_for_ticker":
        return await _list_transcripts_for_ticker(
            session,
            ticker=str(args.get("ticker") or ""),
            limit=int(args.get("limit") or 5),
        )
    if name == "get_transcript_analysis":
        return await _get_transcript_analysis(session, transcript_id=str(args.get("transcript_id") or ""))
    if name == "search_transcript_quotes":
        return await _search_transcript_quotes(
            session,
            query=str(args.get("query") or ""),
            company=str(args.get("company") or "") or None,
        )
    if name == "search_transcripts":
        return await _search_transcripts(
            session,
            company=str(args.get("company") or "") or None,
            q=str(args.get("q") or "") or None,
            topic=str(args.get("topic") or "") or None,
            limit=int(args.get("limit") or 8),
        )
    if name == "company_earnings_timeline":
        return await _company_earnings_timeline(session, ticker=str(args.get("ticker") or ""))
    return {"error": f"unknown tool: {name}"}


async def run_tool_with_events(
    session: AsyncSession,
    name: str,
    args: dict[str, Any],
    emit_tool_start: Any,
    emit_tool_end: Any,
) -> dict[str, Any]:
    await emit_tool_start(name, args)
    t0 = time.monotonic()
    is_error = False
    try:
        result = await execute_ask_earnings_tool(session, name, args)
        if isinstance(result, dict) and result.get("error"):
            is_error = True
    except Exception as e:
        result = {"error": str(e)}
        is_error = True
    duration_ms = int((time.monotonic() - t0) * 1000)
    await emit_tool_end(name, args, result, is_error, duration_ms)
    return result
