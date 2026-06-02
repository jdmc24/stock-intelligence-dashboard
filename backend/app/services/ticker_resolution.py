from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyRegProfile, Transcript
from app.services.sec_ticker_registry import (
    GENERIC_COMPANY_WORDS,
    is_sec_ticker,
    search_sec_companies,
    significant_query_tokens,
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
        "ME",
        "MY",
        "WE",
        "HE",
        "SHE",
        "THEIR",
        "THEM",
        "ANY",
        "ALL",
        "DID",
        "DO",
        "HAD",
        "HAS",
        "WAS",
        "WERE",
        "CAN",
        "MAY",
    }
)

# Common English words that must never become ticker lookups from chat text.
_RESOLUTION_NOISE = frozenset(
    {
        "were",
        "was",
        "most",
        "from",
        "recent",
        "latest",
        "earning",
        "earnings",
        "highlights",
        "highlight",
        "call",
        "calls",
        "what",
        "when",
        "where",
        "which",
        "there",
        "they",
        "them",
        "this",
        "that",
        "with",
        "have",
        "been",
        "said",
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
        "happened",
        "happen",
        "happens",
        "said",
        "talk",
        "talked",
        "discuss",
        "discussed",
        "publicly",
        "traded",
        "stock",
        "stocks",
        "were",
        "was",
        "most",
        "from",
        "recent",
        "highlight",
        "highlights",
        "earning",
    }
)

_CORPORATE_SUFFIX = (
    r"bank|banks|bancshares|bancorp|financial|financials|finance|holdings|holding|group|corp|corporation|inc|plc|co"
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


def _add_ticker(tickers: list[str], seen: set[str], sym: str) -> None:
    t = sym.strip().upper()
    if not t or t in seen or t in _TICKER_STOP:
        return
    seen.add(t)
    tickers.append(t)


def extract_explicit_tickers(text: str, existing: list[str] | None = None) -> list[str]:
    """Extract ticker-like symbols from natural-language questions."""
    tickers: list[str] = []
    seen: set[str] = set()

    for sym in existing or []:
        _add_ticker(tickers, seen, str(sym))

    q = (text or "").strip()
    if not q:
        return tickers

    for m in re.finditer(r"\b([A-Z]{2,5})\b", q):
        _add_ticker(tickers, seen, m.group(1))

    for m in re.finditer(rf"(?i)\b([A-Za-z]{{2,5}})\s+(?:{_CORPORATE_SUFFIX})\b", q):
        _add_ticker(tickers, seen, m.group(1))

    for m in re.finditer(r"(?i)\b(?:ticker|symbol|stock)\s+\$?([A-Za-z]{1,5})\b", q):
        _add_ticker(tickers, seen, m.group(1))

    for m in re.finditer(r"\$([A-Za-z]{1,5})\b", q):
        _add_ticker(tickers, seen, m.group(1))

    return tickers


def _clean_candidate(text: str) -> str:
    s = re.sub(
        r"\b(latest|most recent|earnings call|earnings|conference call|transcript|call|calls|quarter)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"'s\b", "", s, flags=re.IGNORECASE)
    s = " ".join(s.split()).strip()

    tokens = s.split()
    while tokens and tokens[-1].lower() in GENERIC_COMPANY_WORDS:
        tokens.pop()
    while tokens and tokens[0].lower() in GENERIC_COMPANY_WORDS:
        tokens.pop(0)
    return " ".join(tokens).strip()


def _candidate_priority(candidate: str) -> tuple[int, int, int]:
    cleaned = _clean_candidate(candidate)
    sig = significant_query_tokens(cleaned)
    if len(sig) == 1 and 2 <= len(sig[0]) <= 5:
        return (0, len(sig[0]), -len(cleaned))
    if len(sig) <= 2 and len(cleaned.split()) <= 3:
        return (1, len(cleaned), -len(cleaned))
    return (2, len(cleaned), -len(cleaned))


def _candidate_lookup_variants(name: str) -> list[str]:
    cleaned = _clean_candidate(name)
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        v = value.strip()
        key = v.lower()
        if len(key) < 2 or key in seen:
            return
        seen.add(key)
        variants.append(v)

    add(cleaned)
    sig = significant_query_tokens(cleaned)
    if sig:
        add(" ".join(sig))
        add(sig[0])
    for token in sig:
        add(token)
    return variants


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

    for m in re.finditer(rf"(?i)\b([a-zA-Z][\w'.-]{{1,4}})\s+(?:{_CORPORATE_SUFFIX})\b", q):
        candidates.append(_clean_candidate(m.group(1)))

    words = [
        w
        for w in re.findall(r"[a-zA-Z][a-zA-Z'.-]*", q)
        if w.lower().strip("'.") not in _FILLER and len(w.strip("'.") ) >= 2
    ]
    for n in range(4, 1, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i : i + n])
            if len(phrase) >= 5:
                candidates.append(_clean_candidate(phrase))

    for word in words:
        token = word.strip("'.")
        if token.lower() in _FILLER or token.lower() in _RESOLUTION_NOISE:
            continue
        if 3 <= len(token) <= 5 or len(token) >= 5:
            candidates.append(_clean_candidate(token))

    seen: set[str] = set()
    out: list[str] = []
    for candidate in sorted(candidates, key=_candidate_priority):
        key = candidate.lower()
        if key in seen or len(key) < 2:
            continue
        seen.add(key)
        out.append(candidate)
    return out[:16]


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
    for variant in _candidate_lookup_variants(query):
        for hit in await search_sec_companies(variant, limit=limit):
            ticker = str(hit["ticker"])
            existing = merged.get(ticker)
            if existing is None or float(hit["score"]) > float(existing.get("score") or 0):
                merged[ticker] = {**hit, "matched_query": variant}

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


async def _resolve_candidate(
    session: AsyncSession,
    name: str,
    *,
    limit: int = 1,
) -> dict[str, Any] | None:
    cleaned = _clean_candidate(name)
    if cleaned.lower() in _RESOLUTION_NOISE:
        return None
    sig = significant_query_tokens(cleaned)
    if len(sig) == 1 and sig[0] in _RESOLUTION_NOISE:
        return None
    for variant in _candidate_lookup_variants(name):
        if variant.lower() in _RESOLUTION_NOISE:
            continue
        result = await lookup_company_ticker(session, variant, limit=limit)
        matches = result.get("matches") or []
        if not matches:
            continue
        hit = matches[0]
        ticker = str(hit.get("ticker") or "").strip().upper()
        score = float(hit.get("score") or 0)
        min_score = 70.0 if len(sig) == 1 else 55.0
        if ticker and score >= min_score:
            hit = {**hit, "matched_variant": variant}
            return hit
    return None


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
    validated: list[str] = []
    seen: set[str] = set()
    for sym in tickers:
        if not await is_sec_ticker(sym):
            continue
        if sym in seen:
            continue
        seen.add(sym)
        validated.append(sym)
    tickers = validated

    for name in extract_name_candidates(text):
        if len(tickers) >= max_tickers:
            break
        hit = await _resolve_candidate(session, name, limit=1)
        if hit is None:
            continue
        ticker = str(hit.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
        company_name = str(hit.get("company_name") or ticker)
        matched = str(hit.get("matched_variant") or name)
        notes.append(f'Resolved "{matched}" → {ticker} ({company_name[:80]}).')

    return tickers[:max_tickers], notes
