from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass


class EarningsCallError(RuntimeError):
    pass


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
) -> tuple[str, str | None, str | None, list[dict] | None]:
    """
    Returns:
    - raw_text: full transcript string
    - company_name: if available
    - source_url: if available
    - speaker_segments: list of {speaker, title?, text, is_qa?} if available
    """
    try:
        from earningscall import get_company  # type: ignore
        from earningscall.errors import InsufficientApiAccessError  # type: ignore
    except Exception as e:
        raise EarningsCallError(f"earningscall SDK not installed/available: {e}")

    sym = ticker.strip().upper()
    try:
        company = get_company(ticker.lower())
    except InsufficientApiAccessError as e:
        raise EarningsCallError(
            f"{e} Free/demo tier usually includes AAPL and MSFT; other tickers need an EarningsCall API key in backend .env."
        ) from e
    if company is None:
        hint = ""
        if sym == "NIKE":
            hint = " Nike trades under ticker NKE."
        raise EarningsCallError(
            f"Unknown ticker or not available on your EarningsCall plan: {sym}.{hint}"
            " Free tier commonly includes AAPL and MSFT only; other symbols need a paid API key."
        )
    company_name = getattr(company, "name", None) or getattr(company, "company_name", None)

    # Resolve quarter/year
    spec = parse_quarter_label(quarter_label) if quarter_label else None
    specs = [spec] if spec else candidate_quarters(back=12)

    last_err: Exception | None = None
    for s in [x for x in specs if x is not None]:
        try:
            transcript = company.get_transcript(year=s.year, quarter=s.quarter)
            raw_text = getattr(transcript, "text", None)
            if not raw_text:
                raise EarningsCallError("Transcript missing text")

            source_url = getattr(transcript, "url", None) or getattr(transcript, "source_url", None)

            speakers = getattr(transcript, "speakers", None)
            speaker_segments: list[dict] | None = None
            if speakers:
                speaker_segments = []
                for sp in speakers:
                    speaker_segments.append(
                        {
                            "speaker": getattr(sp, "name", None) or getattr(sp, "speaker", None),
                            "title": getattr(sp, "title", None),
                            "text": getattr(sp, "text", None) or "",
                            "is_qa": bool(getattr(sp, "is_qa", False)),
                        }
                    )

            return raw_text, company_name, source_url, speaker_segments
        except Exception as e:
            last_err = e
            continue

    if quarter_label:
        raise EarningsCallError(f"No transcript found for {ticker} {quarter_label}. ({last_err})")
    raise EarningsCallError(f"No recent transcript found for {ticker}. ({last_err})")

