from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from app.settings import settings

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CACHE_TTL_SECONDS = 86_400

_GENERIC_SINGLE = frozenset(
    {
        "bank",
        "banks",
        "financial",
        "finance",
        "services",
        "service",
        "group",
        "holdings",
        "holding",
        "company",
        "corp",
        "inc",
        "the",
        "latest",
        "call",
        "earnings",
    }
)


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
    q = re.sub(r"[^\w\s&'-]", " ", q)
    q = re.sub(r"\b(latest|earnings call|earnings|conference call|transcript|call)\b", " ", q)
    q = re.sub(r"\s+'s\b", " ", q)
    return " ".join(q.split())


async def load_sec_registry(*, force: bool = False) -> list[SecCompanyEntry]:
    global _registry, _registry_loaded_at, _ticker_index

    now = time.monotonic()
    if not force and _registry is not None and now - _registry_loaded_at < _CACHE_TTL_SECONDS:
        return _registry

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate, br",
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


def _score_match(query: str, entry: SecCompanyEntry) -> float:
    q = _normalize_query(query)
    if len(q) < 2:
        return 0.0

    q_up = q.upper()
    if q_up == entry.ticker and 2 <= len(q_up) <= 5:
        return 200.0

    title_norm = _normalize_title(entry.title)
    q_tokens = [t for t in q.split() if len(t) >= 2]
    if not q_tokens:
        return 0.0

    if len(q_tokens) == 1 and q_tokens[0] in _GENERIC_SINGLE:
        return 0.0

    if q in title_norm:
        return 150.0 + len(q)

    title_tokens = set(title_norm.split())
    overlap = [t for t in q_tokens if t in title_tokens]
    if len(q_tokens) >= 2:
        needed = min(2, len(q_tokens))
        if len(overlap) >= needed:
            return 80.0 + len(overlap) * 15.0 + min(len(q), 20)
    elif len(q_tokens) == 1 and len(q_tokens[0]) >= 3:
        token = q_tokens[0]
        if token in title_tokens:
            return 70.0 + len(token)
        if any(token in tt for tt in title_tokens if len(tt) >= 4):
            return 55.0 + len(token)

    return 0.0


async def search_sec_companies(query: str, *, limit: int = 5) -> list[dict[str, str | float]]:
    registry = await load_sec_registry()
    scored: list[tuple[float, SecCompanyEntry]] = []
    for entry in registry:
        score = _score_match(query, entry)
        if score >= 55.0:
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1].ticker))
    out: list[dict[str, str | float]] = []
    for score, entry in scored[: max(1, min(int(limit or 5), 10))]:
        out.append(
            {
                "ticker": entry.ticker,
                "company_name": entry.title,
                "score": round(score, 1),
                "source": "sec",
            }
        )
    return out


async def lookup_ticker(query: str) -> str | None:
    hits = await search_sec_companies(query, limit=1)
    if not hits:
        return None
    return str(hits[0]["ticker"])
