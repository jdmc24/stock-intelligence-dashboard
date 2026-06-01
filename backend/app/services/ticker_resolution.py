from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyRegProfile, Transcript
from app.services.sec_ticker_registry import search_sec_companies

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

_FILLER = frozenset(
    {
        "compare",
        "comparison",
        "the",
        "latest",
        "earnings",
        "call",
        "calls",
        "conference",
        "transcript",
        "for",
        "to",
        "and",
        "vs",
        "versus",
        "how",
        "what",
        "about",
        "their",
        "recent",
        "might",
        "would",
        "could",
        "with",
        "from",
        "that",
        "this",
        "will",
        "they",
        "them",
        "between",
        "across",
        "into",
        "like",
        "when",
        "where",
        "which",
        "while",
        "during",
        "after",
        "before",
        "using",
        "mention",
        "mentioned",
        "did",
        "have",
        "has",
        "any",
        "all",
        "tell",
        "using",
    }
)

LOOKUP_COMPANY_TICKER_TOOL: dict[str, Any] = {
    "name": "lookup_company_ticker",
    "description": (
        "Resolve a company name or informal label to one or more stock tickers. "
        "Uses the SEC public company registry plus names already seen in this app. "
        "Use when the user names a company without a ticker, e.g. 'Huntington Bank' or 'PNC'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {
                "type": "string",
                "description": "Company name, nickname, or phrase from the user's question.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8,
                "description": "Max matches to return (default 3).",
            },
        },
        "required": ["company_name"],
    },
}


def extract_explicit_tickers(text: str, existing: list[str] | None = None) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        t = sym.strip().upper()
        if not t or t in seen or t in _TICKER_STOP:
            return
        seen.add(t)
        tickers.append(t)

    for sym in existing or []:
        add(str(sym))

    q = (text or "").strip()
    if not q:
        return tickers

    for m in re.finditer(r"\b([A-Z]{2,5})\b", q):
        add(m.group(1))

    return tickers


def _clean_candidate(text: str) -> str:
    s = re.sub(
        r"\b(latest|earnings call|earnings|conference call|transcript|call|quarter)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"'s\b", "", s, flags=re.IGNORECASE)
    return " ".join(s.split()).strip()


def extract_name_candidates(text: str) -> list[str]:
    q = (text or "").strip()
    if not q:
        return []

    candidates: list[str] = []

    for pattern in (
        r"\btell me about\s+(.+?)(?:[?.!]|$|\s+(?:are|is|did|do|have|has|was|were)\b)",
        r"\babout\s+([a-zA-Z][\w'.-]*(?:\s+[a-zA-Z][\w'.-]*){0,3})",
        r"\bfor\s+(.+?)\s+to\s+(.+?)(?:'s|\s+(?:latest|earnings|call|quarter))",
        r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:'s|\s+(?:latest|earnings|call|quarter))",
    ):
        match = re.search(pattern, q, re.IGNORECASE)
        if not match:
            continue
        if match.lastindex and match.lastindex >= 2:
            candidates.extend([_clean_candidate(match.group(1)), _clean_candidate(match.group(2))])
        else:
            candidates.append(_clean_candidate(match.group(1)))

    for sep in (r"\bvs\.?\b", r"\bversus\b", r"\bcompared to\b"):
        if re.search(sep, q, re.IGNORECASE):
            for part in re.split(sep, q, flags=re.IGNORECASE):
                cleaned = _clean_candidate(part)
                if cleaned:
                    candidates.append(cleaned)

    words = [
        w
        for w in re.findall(r"[a-zA-Z][a-zA-Z'.-]*", q)
        if w.lower().strip("'.") not in _FILLER and len(w.strip("'.") ) >= 2
    ]
    for n in range(4, 1, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i : i + n])
            if len(phrase) >= 5:
                candidates.append(phrase)

    for word in words:
        token = word.strip("'.")
        if len(token) >= 5 and token.lower() not in _FILLER:
            candidates.append(token)

    seen: set[str] = set()
    out: list[str] = []
    for candidate in sorted(candidates, key=len, reverse=True):
        key = candidate.lower()
        if key in seen or len(key) < 3:
            continue
        seen.add(key)
        out.append(candidate)
    return out[:12]


async def _search_db_companies(session: AsyncSession, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if len(q) < 2:
        return []

    like = f"%{q}%"
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    profile_rows = (
        await session.execute(
            select(CompanyRegProfile)
            .where(CompanyRegProfile.name.ilike(like))
            .order_by(CompanyRegProfile.ticker.asc())
            .limit(limit)
        )
    ).scalars().all()
    for row in profile_rows:
        if row.ticker in seen:
            continue
        seen.add(row.ticker)
        out.append(
            {
                "ticker": row.ticker,
                "company_name": row.name,
                "score": 65.0,
                "source": "profile",
            }
        )

    transcript_rows = (
        await session.execute(
            select(Transcript.ticker, Transcript.company_name)
            .where(Transcript.company_name.is_not(None), Transcript.company_name.ilike(like))
            .group_by(Transcript.ticker, Transcript.company_name)
            .order_by(func.max(Transcript.created_at).desc())
            .limit(limit)
        )
    ).all()
    for ticker, company_name in transcript_rows:
        t = str(ticker or "").strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(
            {
                "ticker": t,
                "company_name": str(company_name or t),
                "score": 60.0,
                "source": "transcript",
            }
        )

    return out[:limit]


async def lookup_company_ticker(
    session: AsyncSession,
    company_name: str,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    query = (company_name or "").strip()
    if len(query) < 2:
        return {"found": False, "note": "company_name too short", "matches": []}

    merged: dict[str, dict[str, Any]] = {}
    for hit in await search_sec_companies(query, limit=limit):
        ticker = str(hit["ticker"])
        merged[ticker] = {**hit, "matched_query": query}

    for hit in await _search_db_companies(session, query, limit=limit):
        ticker = str(hit["ticker"])
        existing = merged.get(ticker)
        if existing is None or float(hit["score"]) > float(existing.get("score") or 0):
            merged[ticker] = {**hit, "matched_query": query}

    matches = sorted(merged.values(), key=lambda x: float(x.get("score") or 0), reverse=True)
    matches = matches[: max(1, min(int(limit or 3), 8))]
    return {
        "found": bool(matches),
        "query": query,
        "count": len(matches),
        "matches": matches,
    }


async def resolve_tickers_for_question(
    session: AsyncSession,
    text: str,
    existing: list[str] | None = None,
    *,
    max_tickers: int = 5,
) -> tuple[list[str], list[str]]:
    """Resolve tickers from explicit symbols and company names in the question."""
    tickers = extract_explicit_tickers(text, existing)
    notes: list[str] = []
    seen = set(tickers)

    for name in extract_name_candidates(text):
        if len(tickers) >= max_tickers:
            break
        result = await lookup_company_ticker(session, name, limit=1)
        matches = result.get("matches") or []
        if not matches:
            continue
        hit = matches[0]
        ticker = str(hit.get("ticker") or "").strip().upper()
        score = float(hit.get("score") or 0)
        if not ticker or ticker in seen or score < 55.0:
            continue
        seen.add(ticker)
        tickers.append(ticker)
        company_name = str(hit.get("company_name") or ticker)
        notes.append(f'Resolved "{name}" → {ticker} ({company_name[:80]}).')

    return tickers[:max_tickers], notes
