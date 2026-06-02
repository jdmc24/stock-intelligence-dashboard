from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from app.settings import settings

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CACHE_TTL_SECONDS = 86_400

# Informal words users add in chat that are not part of SEC company titles.
GENERIC_COMPANY_WORDS = frozenset(
    {
        "bank",
        "banks",
        "bancorp",
        "bancshares",
        "financial",
        "financials",
        "finance",
        "services",
        "service",
        "group",
        "holdings",
        "holding",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "ltd",
        "plc",
        "co",
        "the",
        "latest",
        "call",
        "calls",
        "earnings",
        "stock",
        "stocks",
        "shares",
        "share",
        "publicly",
        "traded",
    }
)

_GENERIC_SINGLE = GENERIC_COMPANY_WORDS


@dataclass(frozen=True)
class SecCompanyEntry:
    ticker: str
    title: str


_registry: list[SecCompanyEntry] | None = None
_registry_loaded_at: float = 0.0
_ticker_index: dict[str, SecCompanyEntry] | None = None


def _normalize_title(title: str) -> str:
    t = title.upper()
    t = re.sub(r"\s+/[^/]*/", " ", t)
    t = re.sub(r"[^\w\s&]", " ", t)
    for suffix in (
        " INC",
        " CORP",
        " CO",
        " LTD",
        " PLC",
        " LP",
        " TRUST",
        " GROUP",
        " HOLDINGS",
        " HOLDING",
        " BANCORP",
        " BANCORPORATION",
    ):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return " ".join(t.split()).lower()


def _normalize_query(query: str) -> str:
    q = query.strip().lower()
    q = re.sub(r"[^\w\s&'$-]", " ", q)
    q = re.sub(r"\$", " ", q)
    q = re.sub(
        r"\b(latest|most recent|earnings call|earnings|conference call|transcript|call|calls|stock|stocks)\b",
        " ",
        q,
    )
    q = re.sub(r"\s+'s\b", " ", q)
    return " ".join(q.split())


def significant_query_tokens(query: str) -> list[str]:
    """Drop generic chat/finance words so 'pnc bank' resolves via the 'pnc' token."""
    q = _normalize_query(query)
    return [t for t in q.split() if len(t) >= 2 and t not in _GENERIC_SINGLE]


async def load_sec_registry(*, force: bool = False) -> list[SecCompanyEntry]:
    global _registry, _registry_loaded_at, _ticker_index

    now = time.monotonic()
    if not force and _registry is not None and now - _registry_loaded_at < _CACHE_TTL_SECONDS:
        return _registry

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
        },
    ) as client:
        response = await client.get(_SEC_TICKERS_URL)
        response.raise_for_status()
        payload = response.json()

    entries: list[SecCompanyEntry] = []
    index: dict[str, SecCompanyEntry] = {}
    for _, row in (payload or {}).items():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        title = str(row.get("title") or "").strip()
        if not ticker or not title:
            continue
        entry = SecCompanyEntry(ticker=ticker, title=title)
        entries.append(entry)
        index[ticker] = entry

    _registry = entries
    _ticker_index = index
    _registry_loaded_at = now
    return entries


async def is_sec_ticker(symbol: str) -> bool:
    sym = (symbol or "").strip().upper()
    if not sym or len(sym) > 5:
        return False
    await load_sec_registry()
    return _ticker_index is not None and sym in _ticker_index


def _score_match(query: str, entry: SecCompanyEntry) -> float:
    q = _normalize_query(query)
    if len(q) < 2:
        return 0.0

    q_compact = q.replace(" ", "").upper()
    if q_compact == entry.ticker and 2 <= len(entry.ticker) <= 5:
        return 200.0

    q_tokens = [t for t in q.split() if len(t) >= 2]
    if not q_tokens:
        return 0.0

    sig_tokens = [t for t in q_tokens if t not in _GENERIC_SINGLE]
    if not sig_tokens:
        return 0.0

    if len(sig_tokens) == 1 and sig_tokens[0] in _GENERIC_SINGLE:
        return 0.0

    if len(sig_tokens) == 1:
        token = sig_tokens[0]
        token_up = token.upper()
        if token_up == entry.ticker and 2 <= len(entry.ticker) <= 5:
            return 195.0

    if q in _normalize_title(entry.title):
        return 150.0 + len(q)

    title_norm = _normalize_title(entry.title)
    title_tokens = set(title_norm.split())
    match_tokens = sig_tokens

    if len(match_tokens) >= 2:
        needed = min(2, len(match_tokens))
        overlap = [t for t in match_tokens if t in title_tokens]
        if len(overlap) >= needed:
            return 80.0 + len(overlap) * 15.0 + min(len(q), 20)
    elif len(match_tokens) == 1 and len(match_tokens[0]) >= 3:
        token = match_tokens[0]
        if token in title_tokens:
            return 70.0 + len(token)
        if any(token in tt for tt in title_tokens if len(tt) >= 4):
            return 55.0 + len(token)

    return 0.0


async def search_sec_companies(query: str, *, limit: int = 5) -> list[dict[str, str | float]]:
    registry = await load_sec_registry()
    scored: list[tuple[float, SecCompanyEntry]] = []

    if _ticker_index is not None:
        for token in significant_query_tokens(query):
            token_up = token.upper()
            if 2 <= len(token_up) <= 5 and token_up in _ticker_index:
                entry = _ticker_index[token_up]
                scored.append((195.0, entry))

    for entry in registry:
        score = _score_match(query, entry)
        if score >= 55.0:
            scored.append((score, entry))

    scored.sort(key=lambda x: (-x[0], x[1].ticker))
    out: list[dict[str, str | float]] = []
    seen: set[str] = set()
    for score, entry in scored:
        if entry.ticker in seen:
            continue
        seen.add(entry.ticker)
        out.append(
            {
                "ticker": entry.ticker,
                "company_name": entry.title,
                "score": round(score, 1),
                "source": "sec",
            }
        )
        if len(out) >= max(1, min(int(limit or 5), 10)):
            break
    return out


async def lookup_ticker(query: str) -> str | None:
    hits = await search_sec_companies(query, limit=1)
    if not hits:
        return None
    return str(hits[0]["ticker"])
