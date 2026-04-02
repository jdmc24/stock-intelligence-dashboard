"""Federal Register API v1 client (https://www.federalregister.gov/reader/api)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

FR_BASE = "https://www.federalregister.gov/api/v1"

# Slugs from regulatory-monitor-prd-v2.md
DEFAULT_AGENCY_SLUGS: tuple[str, ...] = (
    "consumer-financial-protection-bureau",
    "comptroller-of-the-currency",
    "federal-reserve-system",
    "federal-deposit-insurance-corporation",
    "securities-and-exchange-commission",
    "financial-crimes-enforcement-network",
)

# API filter slugs (not the same strings as `type` on each result row).
DEFAULT_DOC_TYPES: tuple[str, ...] = ("RULE", "PRORULE", "NOTICE")


def _build_params(
    *,
    agencies: list[str],
    page: int,
    per_page: int,
    publication_date_gte: dt.date | None,
    publication_date_lte: dt.date | None,
    doc_types: tuple[str, ...] | None,
) -> list[tuple[str, str]]:
    """Federal Register expects repeated keys for array conditions."""
    pairs: list[tuple[str, str]] = []
    for a in agencies:
        pairs.append(("conditions[agencies][]", a))
    dts = doc_types or DEFAULT_DOC_TYPES
    for t in dts:
        pairs.append(("conditions[type][]", t))
    if publication_date_gte is not None:
        pairs.append(("conditions[publication_date][gte]", publication_date_gte.isoformat()))
    if publication_date_lte is not None:
        pairs.append(("conditions[publication_date][lte]", publication_date_lte.isoformat()))
    pairs.append(("per_page", str(per_page)))
    pairs.append(("page", str(page)))
    pairs.append(("order", "newest"))
    return pairs


async def fetch_documents_page(
    *,
    agencies: list[str] | None = None,
    page: int = 1,
    per_page: int = 100,
    publication_date_gte: dt.date | None = None,
    publication_date_lte: dt.date | None = None,
    doc_types: tuple[str, ...] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    ag = list(agencies) if agencies else list(DEFAULT_AGENCY_SLUGS)
    params = _build_params(
        agencies=ag,
        page=page,
        per_page=min(per_page, 1000),
        publication_date_gte=publication_date_gte,
        publication_date_lte=publication_date_lte,
        doc_types=doc_types,
    )
    url = f"{FR_BASE}/documents.json"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_raw_text(raw_text_url: str, timeout: float = 120.0) -> str:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        r = await client.get(raw_text_url)
        r.raise_for_status()
        return r.text


def normalize_fr_result(item: dict[str, Any]) -> dict[str, Any]:
    """Map API JSON item to fields we persist."""
    agencies_raw = item.get("agencies") or []
    agency_labels: list[str] = []
    if isinstance(agencies_raw, list):
        for a in agencies_raw:
            if isinstance(a, dict) and a.get("name"):
                agency_labels.append(str(a["name"]))
            elif isinstance(a, str):
                agency_labels.append(a)

    topics_raw = item.get("topics") or []
    topics: list[str] = []
    if isinstance(topics_raw, list):
        for t in topics_raw:
            if isinstance(t, dict) and t.get("name"):
                topics.append(str(t["name"]))
            elif isinstance(t, str):
                topics.append(t)

    cfr_raw = item.get("cfr_references") or []
    cfr: list[str] = []
    if isinstance(cfr_raw, list):
        for c in cfr_raw:
            if isinstance(c, dict):
                title = c.get("title")
                part = c.get("part")
                if title is not None and part is not None:
                    cfr.append(f"{title} CFR Part {part}")
            elif isinstance(c, str):
                cfr.append(c)

    pub = item.get("publication_date")
    if isinstance(pub, str) and len(pub) >= 10:
        pub_date = dt.date.fromisoformat(pub[:10])
    else:
        pub_date = dt.date.today()

    doc_type = item.get("type") or item.get("document_type") or "Notice"
    if isinstance(doc_type, dict):
        doc_type = doc_type.get("name") or "Notice"
    doc_type_str = str(doc_type)

    return {
        "document_number": str(item.get("document_number") or item.get("id") or ""),
        "title": str(item.get("title") or "(untitled)"),
        "abstract": item.get("abstract"),
        "publication_date": pub_date,
        "document_type": doc_type_str,
        "agencies": agency_labels,
        "federal_register_url": str(item.get("html_url") or ""),
        "pdf_url": item.get("pdf_url"),
        "raw_text_url": item.get("raw_text_url"),
        "html_url": str(item.get("html_url") or ""),
        "cfr_references": cfr,
        "topics": topics,
    }
