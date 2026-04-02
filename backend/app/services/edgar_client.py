from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.settings import settings


class EdgarError(RuntimeError):
    pass


@dataclass(frozen=True)
class EdgarSearchHit:
    title: str
    filed_at: str | None
    link: str | None
    ticker: str | None
    cik: str | None


def _clean_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join([ln for ln in lines if ln])


class EdgarClient:
    """
    V1 approach:
    - Use SEC full-text search (efts) to find likely transcript filings.
    - Fetch the linked document and extract text.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate, br",
            },
        )
        self._ticker_cik_cache: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.8, min=0.8, max=10),
    )
    async def _get_text(self, url: str) -> str:
        r = await self._client.get(url)
        r.raise_for_status()
        return r.text

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.8, min=0.8, max=10),
    )
    async def _get_json(self, url: str) -> Any:
        r = await self._client.get(url)
        r.raise_for_status()
        return r.json()

    async def ticker_to_cik(self, ticker: str) -> str:
        t = ticker.strip().upper()
        if t in self._ticker_cik_cache:
            return self._ticker_cik_cache[t]

        # Phase 1 bootstrap: start with a known-clean company (JPM).
        if t == "JPM":
            self._ticker_cik_cache[t] = "0000019617"
            return self._ticker_cik_cache[t]

        mapping_url = "https://www.sec.gov/files/company_tickers.json"
        data = await self._get_json(mapping_url)
        # Format is a dict keyed by integer-ish strings: { "0": { ticker, cik_str, title }, ... }
        for _, row in (data or {}).items():
            if (row.get("ticker") or "").upper() == t:
                cik_str = str(row.get("cik_str") or "").strip()
                if not cik_str.isdigit():
                    break
                cik10 = cik_str.zfill(10)
                self._ticker_cik_cache[t] = cik10
                return cik10
        raise EdgarError(f"Unable to map ticker to CIK: {t}")

    async def recent_8k_accessions(self, cik10: str, limit: int = 15) -> list[str]:
        sub_url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
        sub = await self._get_json(sub_url)
        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accs = recent.get("accessionNumber") or []
        out: list[str] = []
        for form, acc in zip(forms, accs):
            if form == "8-K":
                out.append(str(acc))
            if len(out) >= limit:
                break
        return out

    async def filing_index(self, cik10: str, accession: str) -> dict[str, Any]:
        cik_int = str(int(cik10))
        acc_nodash = accession.replace("-", "")
        url = f"https://data.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/index.json"
        return await self._get_json(url)

    async def fetch_transcript_from_recent_8k(self, ticker: str) -> tuple[str, str | None]:
        cik10 = await self.ticker_to_cik(ticker)
        accessions = await self.recent_8k_accessions(cik10)
        if not accessions:
            raise EdgarError("No recent 8-K filings found for ticker.")

        cik_int = str(int(cik10))
        for acc in accessions[:10]:
            idx = await self.filing_index(cik10, acc)
            items = (((idx.get("directory") or {}).get("item")) or [])
            # prioritize likely transcript docs
            candidates = []
            for it in items:
                name = (it.get("name") or "").lower()
                if not name:
                    continue
                if not re.search(r"\.(htm|html|txt)$", name):
                    continue
                score = 0
                if "transcript" in name:
                    score += 50
                if "earn" in name:
                    score += 15
                if "ex99" in name or "ex-99" in name or "ex_99" in name:
                    score += 20
                if "press" in name or "release" in name:
                    score += 5
                candidates.append((score, name))
            candidates.sort(reverse=True)

            acc_nodash = acc.replace("-", "")
            for score, name in candidates[:12]:
                url = f"https://data.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{name}"
                try:
                    doc = await self._get_text(url)
                    text = _clean_text_from_html(doc)
                    # Transcripts are typically long; this threshold avoids press releases.
                    if len(text) > 8000:
                        return text, url
                except Exception:
                    continue

        raise EdgarError("Could not find a transcript-like document in recent 8-K filings.")

    async def search_transcripts(
        self,
        ticker: str,
        quarter: str | None = None,
        start: dt.date | None = None,
        end: dt.date | None = None,
        size: int = 20,
    ) -> list[EdgarSearchHit]:
        query_parts = [ticker, "earnings call transcript"]
        if quarter:
            query_parts.append(quarter)
        q = " ".join(query_parts)

        params: dict[str, Any] = {"q": q, "size": size}
        if start and end:
            params.update(
                {
                    "dateRange": "custom",
                    "startdt": start.isoformat(),
                    "enddt": end.isoformat(),
                }
            )

        url = "https://efts.sec.gov/LATEST/search-index"
        r = await self._client.get(url, params=params)
        if r.status_code >= 400:
            raise EdgarError(f"Search failed: {r.status_code}")
        payload = r.json()

        hits: list[EdgarSearchHit] = []
        for h in (payload.get("hits", {}) or {}).get("hits", []) or []:
            src = h.get("_source", {}) or {}
            hits.append(
                EdgarSearchHit(
                    title=str(src.get("title") or src.get("display_names") or ""),
                    filed_at=src.get("file_date"),
                    link=src.get("linkToFilingDetails") or src.get("link") or None,
                    ticker=src.get("ticker") or ticker,
                    cik=src.get("cik") or None,
                )
            )
        return hits

    async def fetch_best_transcript_text(self, ticker: str, quarter: str | None = None) -> tuple[str, str | None]:
        # Prefer structured approach via Submissions + index.json (more reliable than full-text search links).
        try:
            return await self.fetch_transcript_from_recent_8k(ticker=ticker)
        except Exception:
            pass

        # Fallback to full-text search (best-effort, can be noisy).
        today = dt.date.today()
        hits = await self.search_transcripts(
            ticker=ticker,
            quarter=quarter,
            start=today - dt.timedelta(days=365),
            end=today,
            size=20,
        )
        for hit in hits[:5]:
            if not hit.link:
                continue
            try:
                filing_html = await self._get_text(hit.link)
                candidate_urls = _extract_document_urls(filing_html, base_url=hit.link)
                if hit.link not in candidate_urls:
                    candidate_urls.append(hit.link)

                for url in candidate_urls[:12]:
                    try:
                        doc = await self._get_text(url)
                        text = _clean_text_from_html(doc)
                        if len(text) > 8000:
                            return text, url
                    except Exception:
                        continue
            except Exception:
                continue

        raise EdgarError("Found results but could not extract transcript text from EDGAR.")


def _extract_document_urls(filing_details_html: str, base_url: str) -> list[str]:
    """
    Extract likely document URLs from a filing details page.
    Prioritize links with 'transcript' / 'earnings' / 'ex-99' patterns.
    """
    soup = BeautifulSoup(filing_details_html, "lxml")
    urls: list[str] = []

    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        full = urljoin(base_url, href)
        if "sec.gov" not in full:
            continue
        if "/Archives/" not in full and "www.sec.gov" not in full:
            continue
        # Filter to likely document types
        if not re.search(r"\.(htm|html|txt|xml)(\?|$)", full, re.IGNORECASE):
            continue
        urls.append(full)

    # De-dupe preserving order
    seen: set[str] = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]

    def score(u: str) -> int:
        lu = u.lower()
        s = 0
        if "transcript" in lu:
            s += 50
        if "earnings" in lu:
            s += 20
        if "ex99" in lu or "ex-99" in lu or "exhibit" in lu:
            s += 15
        if lu.endswith(".txt"):
            s += 5
        return -s

    urls.sort(key=score)
    return urls

