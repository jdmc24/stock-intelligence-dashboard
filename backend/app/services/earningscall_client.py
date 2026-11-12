from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from dataclasses import dataclass

import httpx

from app.services.sec_ticker_registry import load_sec_registry
from app.settings import settings


class EarningsCallError(RuntimeError):
    pass


# Common mis-parses / aliases → EarningsCall symbol
_TICKER_ALIASES: dict[str, str] = {
    "JPMC": "JPM",
    "JPMORGAN": "JPM",
    "GOOG": "GOOGL",
}


def normalize_earnings_ticker(ticker: str) -> str:
    sym = (ticker or "").strip().upper()
    return _TICKER_ALIASES.get(sym, sym)


@dataclass(frozen=True)
class QuarterSpec:
    year: int
    quarter: int


def parse_quarter_label(label: str) -> QuarterSpec | None:
    """
    Accepts formats like:
    - Q3-2025
    - Q3 2025
    - 2025 Q3
    """
    s = label.strip().upper()
    m = re.search(r"\bQ([1-4])\b", s)
    y = re.search(r"\b(20\d{2})\b", s)
    if not m or not y:
        return None
    return QuarterSpec(year=int(y.group(1)), quarter=int(m.group(1)))


# Cache company symbols and issuer calendars independently of transcript storage.
_PROVIDER_URL = "https://api.earningscall.dev"
_CALL_CACHE_TTL = 900
_SYMBOL_CACHE_TTL = 86400
_call_cache: dict[str, tuple[float, tuple[tuple[str, dt.datetime], ...]]] = {}
_symbols: dict[str, tuple[str, str, str]] = {}
_symbols_loaded = 0.0
_symbols_lock = asyncio.Lock()
_retry_after = 0.0


class EarningsCallBusy(EarningsCallError):
    pass


def _provider_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_PROVIDER_URL,
        timeout=httpx.Timeout(6, connect=3),
        headers={"x-api-key": settings.earningcall_api_key or "demo"},
    )


async def _provider_get(client: httpx.AsyncClient, path: str, **params: str | int) -> dict:
    global _retry_after
    if time.monotonic() < _retry_after:
        raise EarningsCallBusy("The earnings transcript provider is temporarily rate-limited.")
    try:
        response = await client.get(path, params=params)
    except httpx.RequestError as exc:
        raise EarningsCallError("Could not reach the earnings transcript provider.") from exc
    if response.status_code == 429:
        delay = response.headers.get("Retry-After", "6")
        _retry_after = max(_retry_after, time.monotonic() + (int(delay) if delay.isdigit() else 6))
        raise EarningsCallBusy("The earnings transcript provider is temporarily rate-limited.")
    if response.status_code == 404:
        return {}
    if response.is_error:
        raise EarningsCallError(f"Earnings transcript provider returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise EarningsCallError("Invalid response from the earnings transcript provider.") from exc
    if not isinstance(payload, dict):
        raise EarningsCallError("Invalid response from the earnings transcript provider.")
    return payload


def _symbol_key(ticker: str) -> str:
    return ticker.upper().replace(".", "-")


async def _provider_company(client: httpx.AsyncClient, ticker: str) -> tuple[str, str, str]:
    global _symbols, _symbols_loaded
    async with _symbols_lock:
        if not _symbols or time.monotonic() - _symbols_loaded >= _SYMBOL_CACHE_TTL:
            try:
                payload = await _provider_get(client, "/symbols")
                symbols = {}
                for row in payload.get("symbols") or []:
                    symbol = row.get("symbol")
                    exchange = row.get("exchange")
                    if symbol and exchange:
                        symbols.setdefault(_symbol_key(symbol), (exchange, symbol, row.get("name") or symbol))
                if symbols:
                    _symbols, _symbols_loaded = symbols, time.monotonic()
            except EarningsCallError:
                if not _symbols:
                    raise
    key = _symbol_key(ticker)
    if key in _symbols:
        return _symbols[key]
    # A transcript covers the issuer even if the provider catalogs another share class.
    registry = await load_sec_registry()
    cik = next((entry.cik for entry in registry if entry.ticker == ticker), None)
    if cik:
        for entry in registry:
            alternate = _symbol_key(entry.ticker)
            if entry.cik == cik and alternate in _symbols:
                return _symbols[alternate]
    raise EarningsCallError(f"The transcript provider does not list {ticker}.")


async def earnings_call_calendar(ticker: str, *, force: bool = False) -> tuple[tuple[str, dt.datetime], ...]:
    ticker = normalize_earnings_ticker(ticker)
    cached = _call_cache.get(ticker)
    if not force and cached and time.monotonic() - cached[0] < _CALL_CACHE_TTL:
        return cached[1]

    async with _provider_client() as client:
        exchange, symbol, _name = await _provider_company(client, ticker)
        payload = await _provider_get(client, "/events", exchange=exchange, symbol=symbol)
    calls: dict[str, dt.datetime] = {}
    for event in payload.get("events") or []:
        try:
            when = dt.datetime.fromisoformat(event["conference_date"])
            quarter, year = int(event["quarter"]), int(event["year"])
        except (KeyError, TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.UTC)
        label = f"Q{quarter}-{year}"
        if quarter in range(1, 5) and (label not in calls or when > calls[label]):
            calls[label] = when
    result = tuple(sorted(calls.items(), key=lambda item: item[1], reverse=True))
    if result:
        _call_cache[ticker] = time.monotonic(), result
    return result


def candidate_quarters(back: int = 10) -> list[QuarterSpec]:
    """
    Generate recent quarters counting backwards from current quarter.
    """
    today = dt.date.today()
    q = (today.month - 1) // 3 + 1
    year = today.year
    out: list[QuarterSpec] = []
    for _ in range(back):
        out.append(QuarterSpec(year=year, quarter=q))
        q -= 1
        if q == 0:
            q = 4
            year -= 1
    return out


async def fetch_transcript(
    ticker: str,
    quarter_label: str | None = None,
    *,
    max_quarters: int = 12,
) -> tuple[str, str | None, str | None, list[dict] | None, str | None]:
    """
    Returns:
    - raw_text: full transcript string
    - company_name: if available
    - source_url: if available
    - speaker_segments: list of {speaker, title?, text, is_qa?} if available
    - resolved_quarter: label like Q3-2025 when found
    """
    ticker = normalize_earnings_ticker(ticker)
    spec = parse_quarter_label(quarter_label) if quarter_label else None
    specs = [spec] if spec else candidate_quarters(back=max_quarters)

    async with _provider_client() as client:
        exchange, symbol, company_name = await _provider_company(client, ticker)
        for period in specs:
            payload = await _provider_get(
                client, "/transcript", exchange=exchange, symbol=symbol,
                year=period.year, quarter=period.quarter, level=1,
            )
            raw_text = payload.get("text")
            if isinstance(raw_text, str) and raw_text.strip():
                label = f"Q{period.quarter}-{period.year}"
                return raw_text, payload.get("company_name") or company_name, payload.get("url"), None, label

    detail = f" for {quarter_label}" if quarter_label else ""
    raise EarningsCallError(f"No transcript found for {ticker}{detail}.")
