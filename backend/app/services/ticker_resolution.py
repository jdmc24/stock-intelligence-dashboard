from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PROFILES_JSON = Path(__file__).resolve().parent.parent / "data" / "company_profiles.json"

# Names users say in natural language → ticker (beyond static profile names).
_NAME_ALIASES: dict[str, str] = {
    "huntington": "HBAN",
    "huntington bank": "HBAN",
    "huntington bancshares": "HBAN",
    "pnc": "PNC",
    "pnc bank": "PNC",
    "pnc financial": "PNC",
    "jpmorgan": "JPM",
    "jpmorgan chase": "JPM",
    "jp morgan": "JPM",
    "chase": "JPM",
    "bank of america": "BAC",
    "wells fargo": "WFC",
    "goldman sachs": "GS",
    "morgan stanley": "MS",
    "u.s. bancorp": "USB",
    "us bancorp": "USB",
    "truist": "TFC",
    "capital one": "COF",
    "sofi": "SOFI",
}


@lru_cache(maxsize=1)
def _lookup_tables() -> tuple[frozenset[str], dict[str, str]]:
    known: set[str] = set()
    phrase_to_ticker: dict[str, str] = {}

    for phrase, ticker in _NAME_ALIASES.items():
        t = ticker.strip().upper()
        known.add(t)
        phrase_to_ticker[phrase.strip().lower()] = t

    if _PROFILES_JSON.is_file():
        raw = json.loads(_PROFILES_JSON.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for ticker, data in raw.items():
                if not isinstance(data, dict):
                    continue
                t = str(ticker).strip().upper()
                if not t:
                    continue
                known.add(t)
                phrase_to_ticker[t.lower()] = t

                name = str(data.get("name") or "").strip()
                if not name:
                    continue
                nl = name.lower()
                phrase_to_ticker[nl] = t
                parts = nl.split()
                if len(parts) >= 2:
                    phrase_to_ticker[" ".join(parts[:2])] = t

    return frozenset(known), phrase_to_ticker


def resolve_tickers_from_text(text: str, existing: list[str] | None = None) -> list[str]:
    """Resolve tickers from ALL-CAPS symbols and company names in free text."""
    tickers: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        t = sym.strip().upper()
        if not t or t in seen:
            return
        seen.add(t)
        tickers.append(t)

    for sym in existing or []:
        add(str(sym))

    known, phrase_map = _lookup_tables()
    q = (text or "").strip()
    if not q:
        return tickers

    for phrase in sorted(phrase_map.keys(), key=len, reverse=True):
        if len(phrase) < 2:
            continue
        if re.search(rf"\b{re.escape(phrase)}\b", q, re.IGNORECASE):
            add(phrase_map[phrase])

    for m in re.finditer(r"\b([A-Z]{2,5})\b", q):
        add(m.group(1))

    for m in re.finditer(r"\b([A-Za-z]{2,5})\b", q):
        sym = m.group(1).upper()
        if sym in known:
            add(sym)

    return tickers[:5]
