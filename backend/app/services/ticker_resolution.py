from __future__ import annotations

import re
from functools import lru_cache
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

# Names or listing preferences that cannot reliably be inferred from the SEC title.
_COMPANY_ALIASES = {
    "alphabet": "GOOGL",
    "facebook": "META",
    "pepsi": "PEP",
    "google": "GOOGL",
    "huntington bank": "HBAN",
    "jp morgan": "JPM",
    "jpmorgan": "JPM",
    "jpmorgan chase": "JPM",
    "jpmc": "JPM",
    "pnc": "PNC",
    "pnc bank": "PNC",
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
_FUND_TITLE = re.compile(r"\b(?:etf|etn|exchange.traded fund|mutual fund)\b", re.I)
_PARENT_ENDING = re.compile(r" (?:group|holdings?)$")
_INNER_APOSTROPHE = re.compile(r"(?<=\w)[’'](?=\w)")
_NON_COMMON_SYMBOL = re.compile(r"(?:-P[A-Z]*$|-W[A-Z]*$|[-.]U$|[0-9])")

COMPANY_CLARIFICATION_PREFIX = "Which company did you mean by"

_NON_ISSUER_WORDS = frozenset({
    "actual", "analyst", "analysts", "business", "commentary", "demand", "executives", "first",
    "fiscal", "general", "growth", "guidance", "international", "leadership", "management",
    "market", "national", "newest", "operator", "quarter", "recent", "report", "results",
    "revenue", "second", "statement", "third", "today", "transcript", "united",
})
_SUBJECT_INTRO = re.compile(r"\b(?:did|does|do|has|have|is|was|will|would|can|could|should|what|how)\s*$", re.I)
_SUBJECT_PREDICATE = re.compile(
    r"^\s+(?:been\s+)?(?:say|said|saying|report|reported|reporting|announce|announced|discuss|discussed|mention(?:ed)|"
    r"release|share|talk|tell|do|doing|perform|beat|miss|raise|cut|expect|forecast|see|plan|face|respond|"
    r"grow|compare|change|provide|address|comment)\b",
    re.I,
)
_NAME_INTRO = re.compile(
    r"\b(?:tell me about|what about|how about|ask about|compare|summarize|summarise|review|analyze|analyse|recap|research|"
    r"(?:earnings(?: (?:call|report|results|transcript))?|guidance|results|call|transcript|"
    r"summary|highlights|insights|update) (?:of|for|from|on|about)|"
    r"impact (?:on|for)|affect)\s*$",
    re.I,
)
_NAME_TAIL = re.compile(
    r"^(?:\s*$|\s*[?!.,;:]|\s+(?:and|vs\.?|versus|with|to|on|in|for|over|"
    r"earnings|guidance|transcript|results|call|stock|shares|latest|last|Q[1-4])\b)",
    re.I,
)
_COMPARISON = re.compile(r"\b(?:compar(?:e|ed|ing|ison)|vs\.?|versus)\b", re.I)
_COMPARISON_LINK = re.compile(r"(?:\b(?:and|with|to|versus|vs\.?)|[,])\s*$", re.I)


def _is_company_mention(text: str, start: int, end: int) -> bool:
    before, after = text[:start], text[end:]
    if re.match(r"^[’']s\b", after, re.I):
        return True
    if _SUBJECT_INTRO.search(before) and _SUBJECT_PREDICATE.match(after):
        return True
    if not _NAME_TAIL.match(after):
        return False
    return (
        not before.strip()
        or bool(_NAME_INTRO.search(before))
        or bool(_COMPARISON.search(before) and _COMPARISON_LINK.search(before))
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


def _normalized_issuer_name(text: str) -> str:
    title = re.sub(r"\s+/[^/]*(?:/|$)", " ", text)
    name = " ".join(_WORD.findall(_INNER_APOSTROPHE.sub("", title).lower()))
    while (short := _ISSUER_SUFFIX.sub("", name)) != name:
        name = short
    return name


def _issuer_matches(
    name: str,
    matches: set[str],
    entries: dict[str, SecCompanyEntry],
    order: dict[str, int],
    *,
    exact: bool,
) -> set[str]:
    if len(matches) <= 1:
        return matches
    if not exact:
        operating = {t for t in matches if not _FUND_TITLE.search(entries[t].title)}
        matches = operating or matches
        parents = {
            t for t in matches if _PARENT_ENDING.sub("", _normalized_issuer_name(entries[t].title)) == name
        }
        matches = parents or matches

    by_issuer: dict[str, list[str]] = {}
    for ticker in matches:
        entry = entries[ticker]
        by_issuer.setdefault(entry.cik or ticker, []).append(ticker)
    # A call is issuer-level. Prefer ordinary symbols over preferred, warrant and
    # OTC variants, preserving the SEC feed order when listings are otherwise tied.
    return {
        min(symbols, key=lambda t: (
            bool(_NON_COMMON_SYMBOL.search(t)), len(t) == 5 and t.endswith(("F", "Y")), order[t]
        ))
        for symbols in by_issuer.values()
    }


@lru_cache(maxsize=1)
def _issuer_names(registry: tuple[SecCompanyEntry, ...]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    names: dict[str, set[str]] = {}
    prefixes: dict[str, set[str]] = {}
    for entry in registry:
        name = _normalized_issuer_name(entry.title)
        if not name:
            continue
        names.setdefault(name, set()).add(entry.ticker)
        parts = name.split()
        for end in range(1, min(len(parts), 5)):
            prefix = " ".join(parts[:end])
            if len(prefix) >= 3 and parts[end - 1] not in {"a", "and", "of", "the"}:
                prefixes.setdefault(prefix, set()).add(entry.ticker)

        if len(parts) == 2 and len(parts[1]) >= 4:
            prefixes.setdefault(parts[1], set()).add(entry.ticker)

        initials = "".join(word[0] for word in parts if word not in {"and", "of", "the"})
        if len(initials) >= 2 and initials.upper() == entry.ticker:
            prefixes.setdefault(initials, set()).add(entry.ticker)
    return names, prefixes


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

    names, prefixes = _issuer_names(tuple(registry))
    order = {ticker: rank for rank, ticker in enumerate(entries)}
    words = list(_WORD.finditer(text))
    start = 0
    while start < len(words) and len(tickers) < max_tickers:
        candidates: list[tuple[int, set[str]]] = []
        for end in range(start + 1, min(start + 8, len(words)) + 1):
            phrase = text[words[start].start():words[end - 1].end()]
            if re.search(r"[?!;,\n]", phrase):
                break
            name = " ".join(_WORD.findall(_INNER_APOSTROPHE.sub("", phrase).lower()))
            exact = names.get(name)
            if not exact and phrase.lower().endswith(".com") and name.endswith(" com"):
                name = name[:-4]
                exact = names.get(name)
            alias = _COMPANY_ALIASES.get(name)
            if name in GENERIC_COMPANY_WORDS or name in _NON_ISSUER_WORDS or name.upper() in _TICKER_STOP:
                continue
            if not (exact and end - start > 1) and not _is_company_mention(
                text, words[start].start(), words[end - 1].end()
            ):
                continue
            matches = {alias} if alias in entries else exact or prefixes.get(name)
            if matches:
                preferred = matches.intersection(tickers) or _issuer_matches(
                    name, matches, entries, order, exact=bool(exact),
                )
                candidates.append((end, preferred))
        if not candidates:
            start += 1
            continue

        end, matches = candidates[-1]
        phrase = text[words[start].start():words[end - 1].end()]
        start = end
        if len(matches) != 1:
            if not matches.intersection(tickers):
                choices = ", ".join(
                    f"{entries[ticker].title} ({ticker})" for ticker in sorted(matches)[:4]
                )
                notes.append(f'{COMPANY_CLARIFICATION_PREFIX} "{phrase}"? Matches include {choices}.')
            continue
        ticker = next(iter(matches))
        if ticker not in tickers:
            tickers.append(ticker)
            notes.append(f'Resolved "{phrase}" → {ticker} ({entries[ticker].title[:80]}).')
    return tickers, notes
