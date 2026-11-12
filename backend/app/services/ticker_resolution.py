from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyRegProfile, Transcript
from app.services.sec_ticker_registry import (
    GENERIC_COMPANY_WORDS,
    SecCompanyEntry,
    load_sec_registry,
    search_sec_companies,
    significant_query_tokens,
)

_TICKER_STOP = frozenset(
    {
        "A",
        "I",
        "AI",
        "CEO",
        "CFO",
        "EPS",
        "FCF",
        "GAAP",
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
        "SAY",
        "LAST",
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

# Informal names with a known listing. Other names require a complete issuer-name match.
_COMPANY_ALIASES = {
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "apple": "AAPL",
    "costco": "COST",
    "ferrari": "RACE",
    "google": "GOOGL",
    "huntington bank": "HBAN",
    "jp morgan": "JPM",
    "jpmorgan": "JPM",
    "jpmorgan chase": "JPM",
    "jpmc": "JPM",
    "microsoft": "MSFT",
    "nike": "NKE",
    "nvidia": "NVDA",
    "pnc": "PNC",
    "pnc bank": "PNC",
    "tesla": "TSLA",
    "uber": "UBER",
}
_ISSUER_SUFFIX = re.compile(
    r" (?:n v|incorporated|inc|corporation|corp|company|co|limited|ltd|plc|llc|lp|ag|sa|se)$"
)
_MARKED_SYMBOL = re.compile(
    r"(?<![\w$])(?:\$|(?i:\b(?:ticker|symbol)\s+)\$?)"
    r"([A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?)(?!\w)"
)
_BARE_SYMBOL = re.compile(r"(?<![\w$])([A-Z]{2,5}(?:[.-][A-Z]{1,2})?)(?!\w)")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

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
    """Read marked symbols and unambiguous uppercase ticker tokens."""
    symbols = [str(t).strip().upper() for t in existing or [] if str(t).strip()]
    marked = list(_MARKED_SYMBOL.finditer(text))
    matches = [(m.start(1), m.group(1).upper()) for m in marked]
    for match in _BARE_SYMBOL.finditer(text):
        symbol = match.group(1)
        if symbol in _TICKER_STOP or any(m.start() <= match.start() < m.end() for m in marked):
            continue
        matches.append((match.start(), symbol))
    return list(dict.fromkeys([*symbols, *(symbol for _, symbol in sorted(matches))]))


def _issuer_names(registry: list[SecCompanyEntry]) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for entry in registry:
        title = re.sub(r"\s+/[^/]*/", " ", entry.title)
        full = " ".join(_WORD.findall(title.lower()))
        short = _ISSUER_SUFFIX.sub("", full)
        while short != full:
            full, short = short, _ISSUER_SUFFIX.sub("", short)
        if short and short not in GENERIC_COMPANY_WORDS and short.upper() not in _TICKER_STOP:
            names.setdefault(short, set()).add(entry.ticker)
    return names


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


async def resolve_tickers_for_question(
    session: AsyncSession,
    text: str,
    existing: list[str] | None = None,
    *,
    max_tickers: int = 5,
) -> tuple[list[str], list[str]]:
    """Resolve Ask entities without the fuzzy, interactive company-search fallback."""
    registry = await load_sec_registry()
    entries = {entry.ticker: entry for entry in registry}
    tickers = [
        ticker for ticker in dict.fromkeys(
            t if t in entries else t.replace(".", "-") for t in extract_explicit_tickers(text, existing)
        ) if ticker in entries
    ]
    notes: list[str] = []
    if len(tickers) >= max_tickers:
        return tickers[:max_tickers], notes

    names = _issuer_names(registry)
    words = list(_WORD.finditer(text))
    start = 0
    while start < len(words) and len(tickers) < max_tickers:
        candidates: list[tuple[int, set[str]]] = []
        for end in range(start + 1, min(start + 8, len(words)) + 1):
            phrase = text[words[start].start():words[end - 1].end()]
            if re.search(r"[?!;,\n]", phrase):
                break
            name = " ".join(word.group().lower() for word in words[start:end])
            alias = _COMPANY_ALIASES.get(name)
            if alias in entries:
                candidates.append((end, {alias}))
            elif name in names and (end - start > 1 or phrase[0].isupper()):
                candidates.append((end, names[name]))
        if not candidates:
            start += 1
            continue

        end, matches = candidates[-1]
        phrase = text[words[start].start():words[end - 1].end()]
        start = end
        if len(matches) != 1:
            if not matches.intersection(tickers):
                notes.append(f'Company name "{phrase}" is ambiguous. Include its ticker symbol.')
            continue
        ticker = next(iter(matches))
        if ticker not in tickers:
            tickers.append(ticker)
            notes.append(f'Resolved "{phrase}" → {ticker} ({entries[ticker].title[:80]}).')
    return tickers, notes
