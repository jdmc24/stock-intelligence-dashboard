from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.services.sec_ticker_registry import load_sec_registry
from app.settings import settings

_EDGAR_DATA = "https://data.sec.gov"
_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_FILENAME = re.compile(r"^[\w.-]+\.html?$", re.I)
_PERIOD_END = re.compile(
    r"\bended\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+20\d{2})", re.I
)


@dataclass(frozen=True)
class EarningsFiling:
    ticker: str
    quarter: str | None
    kind: str
    label: str
    url: str
    accession: str
    period_end: dt.date
    text: str


@dataclass(frozen=True)
class _Filing:
    form: str
    accession: str
    document: str
    reported: dt.date
    filed: dt.date
    items: str


def _recent_filings(submissions: dict) -> list[_Filing]:
    recent = submissions.get("filings", {}).get("recent", {})
    result = []
    for form, accession, document, reported, filed, items in zip(
        *(recent.get(key, []) for key in (
            "form", "accessionNumber", "primaryDocument", "reportDate", "filingDate", "items"
        ))
    ):
        if form not in {"8-K", "10-Q", "10-K"} or not _ACCESSION.fullmatch(accession) or not _FILENAME.fullmatch(document):
            continue
        try:
            result.append(_Filing(form, accession, document, dt.date.fromisoformat(reported), dt.date.fromisoformat(filed), items))
        except ValueError:
            continue
    return result


def _fiscal_period(period_end: dt.date, fiscal_year_end: str, *, annual: bool = False) -> str | None:
    if not re.fullmatch(r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])", fiscal_year_end):
        return None
    month, day = int(fiscal_year_end[:2]), int(fiscal_year_end[2:])
    candidates = []
    for year in range(period_end.year - 1, period_end.year + 2):
        for quarter in ([4] if annual else [1, 2, 3, 4]):
            nominal_year, nominal_month = divmod(year * 12 + month - 1 - 3 * (4 - quarter), 12)
            nominal_month += 1
            end = dt.date(nominal_year, nominal_month, min(day, calendar.monthrange(nominal_year, nominal_month)[1]))
            candidates.append((abs((end - period_end).days), quarter, year))
    difference, quarter, year = min(candidates)
    return f"Q{quarter}-{year}" if difference <= 35 else None


def _matches_period(quarter: str | None, requested: str | None) -> bool:
    return not requested or quarter == requested or bool(
        len(requested) == 2 and quarter and quarter.startswith(f"{requested}-")
    )


def _archive_url(cik: str, filing: _Filing) -> str:
    return f"{_EDGAR_ARCHIVES}/{int(cik)}/{filing.accession.replace('-', '')}/{filing.document}"


def _release_exhibit(html: str, archive_url: str) -> tuple[str | None, dt.date | None]:
    page = BeautifulSoup(html, "lxml")
    date_match = _PERIOD_END.search(" ".join(page.stripped_strings))
    period = None
    if date_match:
        try:
            period = dt.datetime.strptime(date_match[1], "%B %d, %Y").date()
        except ValueError:
            pass

    base = urlsplit(archive_url)
    directory = base.path.rsplit("/", 1)[0] + "/"
    for link in page.find_all("a", href=True):
        label = link.get_text(" ", strip=True)
        if not re.search(r"\b99\.1\b|(?:earnings|press|news) release", label, re.I):
            continue
        candidate = urlsplit(urljoin(archive_url, link["href"]))
        filename = candidate.path.removeprefix(directory)
        if (candidate.scheme, candidate.netloc) == (base.scheme, base.netloc) and candidate.path.startswith(directory) and _FILENAME.fullmatch(filename):
            return f"{_EDGAR_ARCHIVES}/{directory.split('/data/', 1)[1]}{filename}", period
    return None, period


def _exhibit_text(html: str) -> str:
    page = BeautifulSoup(html, "lxml")
    for tag in page.find_all(["script", "style", "ix:header", "ix:hidden"]):
        tag.decompose()
    for row in page.find_all("tr"):
        cells = [" ".join(cell.stripped_strings) for cell in row.find_all(["td", "th"], recursive=False)]
        if cells:
            row.replace_with(" | ".join(cell for cell in cells if cell))
    return "\n".join(line.strip() for line in page.get_text("\n").splitlines() if line.strip())[:18000]


_METRICS = {
    "Revenue": ("Revenues", "SalesRevenueNet", "Revenue"),
    "Revenue from customer contracts": ("RevenueFromContractWithCustomerExcludingAssessedTax",),
    "Operating income (loss)": ("OperatingIncomeLoss", "ProfitLossFromOperatingActivities"),
    "Net income (loss)": ("NetIncomeLoss", "ProfitLoss"),
    "Diluted earnings per share": ("EarningsPerShareDiluted", "DilutedEarningsLossPerShare"),
    "Cash from operating activities": ("NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"),
    "Cash and cash equivalents": ("CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"),
}


def _reported_quarters(payload: dict, reports: list[_Filing]) -> dict[str, str]:
    report_dates = {report.accession: report.reported.isoformat() for report in reports}
    labels: dict[str, set[str]] = {}
    for taxonomy in payload.get("facts", {}).values():
        for concept in taxonomy.values():
            for values in concept.get("units", {}).values():
                for value in values:
                    accession = value.get("accn")
                    if accession not in report_dates or value.get("end") != report_dates[accession]:
                        continue
                    period, year = value.get("fp"), value.get("fy")
                    if period == "FY":
                        period = "Q4"
                    if re.fullmatch(r"Q[1-4]", str(period)) and isinstance(year, int):
                        labels.setdefault(accession, set()).add(f"{period}-{year}")
    return {accession: next(iter(quarters)) for accession, quarters in labels.items() if len(quarters) == 1}


def _fiscal_year_offset(reports: list[_Filing], verified: dict[str, str], fiscal_end: str) -> int | None:
    offsets = set()
    for report in reports:
        actual = verified.get(report.accession)
        estimated = _fiscal_period(report.reported, fiscal_end, annual=report.form == "10-K")
        if actual and estimated and actual[:2] == estimated[:2]:
            offsets.add(int(actual[3:]) - int(estimated[3:]))
    return next(iter(offsets)) if len(offsets) == 1 else None


def _filing_facts(payload: dict, filing: _Filing) -> tuple[str, str | None]:
    facts = payload.get("facts", {})
    concepts = {**facts.get("ifrs-full", {}), **facts.get("us-gaap", {})}
    label = None
    lines = []
    for metric, aliases in _METRICS.items():
        for alias in aliases:
            candidates = []
            for unit, values in concepts.get(alias, {}).get("units", {}).items():
                for value in values:
                    if value.get("accn") != filing.accession or value.get("end") != filing.reported.isoformat():
                        continue
                    if not isinstance(value.get("val"), (int, float)):
                        continue
                    try:
                        start = dt.date.fromisoformat(value["start"]) if value.get("start") else None
                    except ValueError:
                        continue
                    duration = (filing.reported - start).days if start else 0
                    candidates.append((duration, start, unit, value))
            if not candidates:
                continue
            _, start, unit, value = min(candidates, key=lambda item: item[0])
            if re.fullmatch(r"Q[1-4]", str(value.get("fp", ""))) and isinstance(value.get("fy"), int):
                label = f"{value['fp']}-{value['fy']}"
            window = f"{start.isoformat()} through {filing.reported.isoformat()}" if start else f"as of {filing.reported.isoformat()}"
            lines.append(f"{metric} ({window}): {value['val']:,} {unit}.")
            break
    return "\n".join(lines), label


async def fetch_earnings_filing(ticker: str, requested_quarter: str | None) -> EarningsFiling | None:
    """Prefer an issuer's SEC-filed earnings release, then facts tied to its 10-Q."""
    registry = await load_sec_registry()
    cik = next((entry.cik for entry in registry if entry.ticker == ticker), None)
    if not cik:
        return None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(4, connect=2),
        headers={"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"},
    ) as client:
        response = await client.get(f"{_EDGAR_DATA}/submissions/CIK{cik.zfill(10)}.json")
        response.raise_for_status()
        submissions = response.json()
        fiscal_end = submissions.get("fiscalYearEnd") or ""
        filings = _recent_filings(submissions)
        reports = sorted(
            (f for f in filings if f.form in {"10-Q", "10-K"}),
            key=lambda f: (f.reported, f.filed), reverse=True,
        )
        facts = {}
        if reports:
            try:
                response = await client.get(f"{_EDGAR_DATA}/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json")
                response.raise_for_status()
                facts = response.json()
            except (httpx.HTTPError, ValueError):
                pass
        verified = _reported_quarters(facts, reports)
        quarters_by_date = {
            filing.reported: verified[filing.accession] for filing in reversed(reports) if filing.accession in verified
        }
        year_offset = _fiscal_year_offset(reports, verified, fiscal_end)

        def quarter_for_date(reported: dt.date) -> str | None:
            if reported in quarters_by_date:
                return quarters_by_date[reported]
            estimated = _fiscal_period(reported, fiscal_end)
            if estimated and year_offset is not None:
                return f"{estimated[:2]}-{int(estimated[3:]) + year_offset}"
            return None

        report = next((
            f for f in reports if _matches_period(quarter_for_date(f.reported), requested_quarter)
        ), None)

        releases = [
            f for f in filings if f.form == "8-K" and "2.02" in f.items.split(",")
            and (not report or -45 <= (f.filed - report.filed).days <= 7
                 or not requested_quarter and f.filed > report.filed)
        ]
        for release in sorted(releases, key=lambda f: f.filed, reverse=True)[:2]:
            try:
                cover = await client.get(_archive_url(cik, release))
                if cover.status_code in {401, 403, 429}:
                    break
                cover.raise_for_status()
                exhibit_url, reported = await asyncio.to_thread(_release_exhibit, cover.text, str(cover.url))
                if not exhibit_url:
                    continue
                if not reported or reported > release.filed or report and reported < report.reported:
                    continue
                quarter = quarter_for_date(reported)
                if not _matches_period(quarter, requested_quarter):
                    continue
                exhibit = await client.get(exhibit_url)
                exhibit.raise_for_status()
                text = await asyncio.to_thread(_exhibit_text, exhibit.text)
                if len(text) > 300 and re.search(r"\b(?:revenue|earnings|financial results|net income)\b", text, re.I):
                    return EarningsFiling(
                        ticker, quarter, "earnings_release", "Earnings release", exhibit_url, release.accession, reported, text
                    )
            except httpx.HTTPError:
                continue

        if not report or report.form != "10-Q":
            return None
        text, verified_period = _filing_facts(facts, report)
        quarter = verified_period or quarter_for_date(report.reported)
        if text and _matches_period(quarter, requested_quarter):
            return EarningsFiling(
                ticker, quarter, "sec_filing", "Form 10-Q", _archive_url(cik, report), report.accession, report.reported, text
            )
        return None
