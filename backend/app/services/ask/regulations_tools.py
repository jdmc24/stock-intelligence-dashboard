from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.regulatory_tools import (
    TOOLS as BASE_REG_TOOLS,
    _lookup_company_profile,
    _search_related_regulations,
)
from app.services.regulations_service import impact_by_ticker, list_documents

# Phase 2 will add earnings tools here (search_transcripts, get_analysis, …).

ASK_REG_TOOLS: list[dict[str, Any]] = [
    *BASE_REG_TOOLS,
    {
        "name": "impact_by_ticker",
        "description": (
            "Find enriched Federal Register documents that overlap a company's regulatory profile "
            "(products, functions, institution types) within a lookback window. "
            "Prefer this when the user names a ticker and wants relevant rules."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. MSFT, JPM."},
                "lookback_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Publication window in days (default 90).",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "list_regulations",
        "description": (
            "Keyword search over ingested Federal Register documents (title/abstract/body). "
            "Use for topic-led questions when impact_by_ticker is not enough."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Keyword phrase."},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Max documents (default 5).",
                },
            },
            "required": ["search"],
        },
    },
]


async def _impact_by_ticker_tool(
    session: AsyncSession,
    ticker: str,
    lookback_days: int = 90,
) -> dict[str, Any]:
    t = (ticker or "").strip().upper()
    if not t:
        return {"found": False, "note": "empty ticker"}
    data = await impact_by_ticker(session, t, lookback_days=max(1, min(int(lookback_days or 90), 365)))
    if data is None:
        return {"found": False, "ticker": t, "note": "No company profile — seed company_reg_profiles first."}
    matches = []
    for m in (data.get("matches") or [])[:8]:
        mr = m.get("match_reason") or {}
        matches.append(
            {
                "id": m.get("id"),
                "document_number": m.get("document_number"),
                "title": (m.get("title") or "")[:200],
                "publication_date": m.get("publication_date"),
                "severity": (m.get("enrichment") or {}).get("severity"),
                "summary": ((m.get("enrichment") or {}).get("summary") or "")[:400],
                "link_types": mr.get("link_types") or [],
            }
        )
    return {
        "found": True,
        "ticker": t,
        "company_name": data.get("company_name"),
        "lookback_days": data.get("lookback_days"),
        "match_count": len(matches),
        "matches": matches,
    }


async def _list_regulations_tool(session: AsyncSession, search: str, limit: int = 5) -> dict[str, Any]:
    q = (search or "").strip()
    if not q:
        return {"matches": [], "count": 0, "note": "empty search"}
    n = max(1, min(int(limit or 5), 10))
    items, total = await list_documents(session, search=q, page=1, per_page=n)
    matches = []
    for m in items:
        matches.append(
            {
                "id": m.get("id"),
                "document_number": m.get("document_number"),
                "title": (m.get("title") or "")[:200],
                "publication_date": m.get("publication_date"),
                "severity": (m.get("enrichment") or {}).get("severity"),
                "summary_excerpt": ((m.get("enrichment") or {}).get("summary") or "")[:300],
            }
        )
    return {"matches": matches, "count": len(matches), "total": total, "search": q}


async def execute_ask_reg_tool(session: AsyncSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    args = arguments or {}
    if name == "search_related_regulations":
        return await _search_related_regulations(
            session,
            query=str(args.get("query") or ""),
            limit=int(args.get("limit") or 5),
        )
    if name == "lookup_company_profile":
        return await _lookup_company_profile(session, ticker=str(args.get("ticker") or ""))
    if name == "impact_by_ticker":
        return await _impact_by_ticker_tool(
            session,
            ticker=str(args.get("ticker") or ""),
            lookback_days=int(args.get("lookback_days") or 90),
        )
    if name == "list_regulations":
        return await _list_regulations_tool(
            session,
            search=str(args.get("search") or ""),
            limit=int(args.get("limit") or 5),
        )
    return {"error": f"unknown tool: {name}"}


TOOL_LABELS: dict[str, str] = {
    "lookup_company_profile": "Looked up company profile",
    "search_related_regulations": "Searched related regulations",
    "impact_by_ticker": "Matched regulations to ticker profile",
    "list_regulations": "Searched regulation catalog",
}


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
        result = await execute_ask_reg_tool(session, name, args)
        if isinstance(result, dict) and result.get("error"):
            is_error = True
    except Exception as e:
        result = {"error": str(e)}
        is_error = True
    duration_ms = int((time.monotonic() - t0) * 1000)
    await emit_tool_end(name, args, result, is_error, duration_ms)
    return result
