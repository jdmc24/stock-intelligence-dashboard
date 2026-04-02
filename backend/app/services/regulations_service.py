from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyRegProfile, RegDocument, RegEnrichment
from app.settings import settings
from app.services.federal_register import (
    DEFAULT_AGENCY_SLUGS,
    DEFAULT_DOC_TYPES,
    fetch_documents_page,
    fetch_raw_text,
    normalize_fr_result,
)
from app.services.regulations_db import ensure_reg_search_fts

logger = logging.getLogger(__name__)

_COMPANY_PROFILES_JSON = Path(__file__).resolve().parent.parent / "data" / "company_profiles.json"


async def seed_company_profiles(session: AsyncSession) -> int:
    """Load JSON profiles into company_reg_profiles if table is empty."""
    n = await session.scalar(select(func.count()).select_from(CompanyRegProfile))
    if n and n > 0:
        return 0
    with _COMPANY_PROFILES_JSON.open(encoding="utf-8") as f:
        data = json.load(f)
    inserted = 0
    for ticker, row in data.items():
        if not isinstance(row, dict):
            continue
        t = ticker.strip().upper()
        session.add(
            CompanyRegProfile(
                ticker=t,
                name=str(row.get("name") or t),
                institution_types=json.dumps(row.get("institution_types") or []),
                primary_products=json.dumps(row.get("primary_products") or []),
                primary_functions=json.dumps(row.get("primary_functions") or []),
                gics_sector=row.get("gics_sector"),
                gics_sub_industry=row.get("gics_sub_industry"),
                is_auto_generated=False,
                user_overrides=None,
            )
        )
        inserted += 1
    await session.commit()
    return inserted


async def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one("#agency-content") or soup.select_one(".doc-content") or soup.article or soup.body
    if not node:
        return soup.get_text("\n", strip=True)
    return node.get_text("\n", strip=True)


async def _fetch_full_text(norm: dict[str, Any]) -> str:
    raw_url = norm.get("raw_text_url")
    if isinstance(raw_url, str) and raw_url.startswith("http"):
        try:
            return await fetch_raw_text(raw_url)
        except Exception as e:
            logger.warning("raw_text fetch failed for %s: %s", norm.get("document_number"), e)

    html_url = norm.get("html_url") or norm.get("federal_register_url")
    if isinstance(html_url, str) and html_url.startswith("http"):
        try:
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                r = await client.get(html_url)
                r.raise_for_status()
            return await _html_to_text(r.text)
        except Exception as e:
            logger.warning("html fetch failed for %s: %s", norm.get("document_number"), e)

    abstract = norm.get("abstract")
    if isinstance(abstract, str) and abstract.strip():
        return abstract.strip()
    return ""


@dataclass
class IngestResult:
    pages_fetched: int
    candidates: int
    inserted: int
    skipped_existing: int
    errors: int
    date_start: dt.date
    date_end: dt.date


async def run_federal_register_ingest(
    session: AsyncSession,
    *,
    days: int = 1,
    per_page: int = 100,
    max_pages: int = 30,
    agencies: list[str] | None = None,
) -> IngestResult:
    """Fetch documents published in the last `days` calendar days (inclusive)."""
    end = dt.date.today()
    start = end - dt.timedelta(days=max(days - 1, 0))

    ag = list(agencies) if agencies else list(DEFAULT_AGENCY_SLUGS)
    doc_types = DEFAULT_DOC_TYPES

    inserted = 0
    skipped = 0
    errors = 0
    candidates = 0
    pages = 0

    page = 1
    while page <= max_pages:
        data = await fetch_documents_page(
            agencies=ag,
            page=page,
            per_page=per_page,
            publication_date_gte=start,
            publication_date_lte=end,
            doc_types=doc_types,
        )
        results = data.get("results") or []
        pages += 1
        if not results:
            break

        for item in results:
            if not isinstance(item, dict):
                continue
            norm = normalize_fr_result(item)
            dnum = norm["document_number"].strip()
            if not dnum:
                errors += 1
                continue
            candidates += 1

            existing = await session.scalar(select(RegDocument).where(RegDocument.document_number == dnum))
            if existing:
                skipped += 1
                continue

            text_body = await _fetch_full_text(norm)
            if len(text_body.strip()) < 20:
                errors += 1
                logger.warning("insufficient text for document %s", dnum)
                continue

            doc = RegDocument(
                document_number=dnum,
                title=norm["title"],
                abstract=norm.get("abstract") if isinstance(norm.get("abstract"), str) else None,
                publication_date=norm["publication_date"],
                document_type=norm["document_type"],
                agencies=json.dumps(norm["agencies"]),
                federal_register_url=norm["federal_register_url"],
                pdf_url=norm.get("pdf_url") if isinstance(norm.get("pdf_url"), str) else None,
                raw_text=text_body,
                cfr_references=json.dumps(norm["cfr_references"]),
                fr_topics=json.dumps(norm["topics"]),
                search_text=None,
                status="raw",
            )
            session.add(doc)
            await session.flush()
            inserted += 1

        await session.commit()

        if len(results) < per_page:
            break
        page += 1
        await asyncio.sleep(1.0)

    return IngestResult(
        pages_fetched=pages,
        candidates=candidates,
        inserted=inserted,
        skipped_existing=skipped,
        errors=errors,
        date_start=start,
        date_end=end,
    )


def _doc_to_dict(doc: RegDocument, enrichment: RegEnrichment | None) -> dict[str, Any]:
    agencies = json.loads(doc.agencies) if doc.agencies else []
    cfr = json.loads(doc.cfr_references) if doc.cfr_references else []
    topics = json.loads(doc.fr_topics) if doc.fr_topics else []
    out: dict[str, Any] = {
        "id": doc.id,
        "document_number": doc.document_number,
        "title": doc.title,
        "abstract": doc.abstract,
        "publication_date": doc.publication_date.isoformat(),
        "document_type": doc.document_type,
        "agencies": agencies,
        "federal_register_url": doc.federal_register_url,
        "pdf_url": doc.pdf_url,
        "cfr_references": cfr,
        "topics": topics,
        "status": doc.status,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
    if enrichment:
        out["enrichment"] = {
            "summary": enrichment.summary,
            "change_type": enrichment.change_type,
            "effective_date": enrichment.effective_date.isoformat() if enrichment.effective_date else None,
            "severity": enrichment.severity,
            "affected_products": json.loads(enrichment.affected_products or "[]"),
            "affected_functions": json.loads(enrichment.affected_functions or "[]"),
        }
    else:
        out["enrichment"] = None
    return out


def _documents_filters(
    *,
    doc_type: str | None,
    search: str | None,
    agency_substring: str | None,
):
    def apply(stmt):
        if doc_type:
            stmt = stmt.where(RegDocument.document_type == doc_type)
        if search and search.strip():
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    RegDocument.title.ilike(term),
                    RegDocument.abstract.ilike(term),
                    RegDocument.raw_text.ilike(term),
                    RegDocument.search_text.ilike(term),
                )
            )
        if agency_substring and agency_substring.strip():
            sub = agency_substring.strip().lower()
            stmt = stmt.where(RegDocument.agencies.ilike(f"%{sub}%"))
        return stmt

    return apply


async def list_documents(
    session: AsyncSession,
    *,
    agency_substring: str | None = None,
    doc_type: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    apply_f = _documents_filters(doc_type=doc_type, search=search, agency_substring=agency_substring)

    cq = apply_f(select(func.count()).select_from(RegDocument))
    total = (await session.execute(cq)).scalar() or 0

    q = apply_f(
        select(RegDocument, RegEnrichment).outerjoin(RegEnrichment, RegEnrichment.document_id == RegDocument.id)
    )
    q = q.order_by(RegDocument.publication_date.desc(), RegDocument.created_at.desc())
    offset = max(page - 1, 0) * per_page
    q = q.offset(offset).limit(per_page)

    rows = (await session.execute(q)).all()
    out = [_doc_to_dict(d, e) for d, e in rows]
    return out, total


async def get_document(session: AsyncSession, doc_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(RegDocument, RegEnrichment)
            .outerjoin(RegEnrichment, RegEnrichment.document_id == RegDocument.id)
            .where(RegDocument.id == doc_id)
        )
    ).one_or_none()
    if not row:
        return None
    d, e = row[0], row[1]
    data = _doc_to_dict(d, e)
    data["raw_text"] = d.raw_text
    if e:
        data["enrichment_full"] = {
            "summary": e.summary,
            "change_type": e.change_type,
            "effective_date": e.effective_date.isoformat() if e.effective_date else None,
            "comment_deadline": e.comment_deadline.isoformat() if e.comment_deadline else None,
            "compliance_deadline": e.compliance_deadline.isoformat() if e.compliance_deadline else None,
            "is_final": e.is_final,
            "severity": e.severity,
            "severity_rationale": e.severity_rationale,
            "affected_products": json.loads(e.affected_products or "[]"),
            "affected_functions": json.loads(e.affected_functions or "[]"),
            "institution_types": json.loads(e.institution_types or "[]"),
            "provisions": json.loads(e.provisions or "[]"),
            "model_used": e.model_used,
            "prompt_version": e.prompt_version,
        }
    return data


async def regulations_status(session: AsyncSession) -> dict[str, Any]:
    """Aggregate pipeline health for ingest → enrich → ticker matching."""
    n = await session.scalar(select(func.count()).select_from(RegDocument)) or 0
    n_enriched = (
        await session.scalar(
            select(func.count()).select_from(RegDocument).where(RegDocument.status == "enriched")
        )
        or 0
    )
    n_raw = await session.scalar(select(func.count()).select_from(RegDocument).where(RegDocument.status == "raw")) or 0
    n_processing = (
        await session.scalar(
            select(func.count()).select_from(RegDocument).where(RegDocument.status == "processing")
        )
        or 0
    )
    n_err = await session.scalar(select(func.count()).select_from(RegDocument).where(RegDocument.status == "error")) or 0
    last_ingest = await session.scalar(select(func.max(RegDocument.created_at)))
    last_enrichment = await session.scalar(select(func.max(RegEnrichment.created_at)))
    n_profiles = await session.scalar(select(func.count()).select_from(CompanyRegProfile)) or 0

    anthropic_ok = bool(settings.anthropic_api_key and str(settings.anthropic_api_key).strip())

    coverage: float | None = None
    if n > 0:
        coverage = round(100.0 * float(n_enriched) / float(n), 1)

    warnings: list[str] = []
    if n == 0:
        warnings.append("No Federal Register documents — run POST /api/regulations/ingest/trigger (e.g. days=3).")
    if not anthropic_ok:
        warnings.append("ANTHROPIC_API_KEY is not set — LLM enrichment cannot run.")
    if n_raw > 0:
        warnings.append(f"{n_raw} document(s) in raw queue — POST /api/regulations/enrich/trigger to classify and tag.")
    if n_processing > 0:
        warnings.append(
            f"{n_processing} document(s) in processing — if this persists, check logs or reset status to raw/error."
        )
    if n_err > 0:
        if n > 0 and n_err == n and n_raw == 0 and n_processing == 0:
            warnings.append(
                "Every document is in error — check ANTHROPIC/API logs, then POST …/reprocess/{id} or reset status to raw."
            )
        else:
            warnings.append(f"{n_err} document(s) in error after a failed enrichment — reprocess or reset to raw.")
    if n_profiles == 0 and n > 0:
        warnings.append("No company_reg_profiles — ticker impact (GET …/impact/by-ticker/{t}) returns 404 until seeded.")

    backlog = n_raw + n_processing
    enrichment_pipeline_ok = anthropic_ok and backlog == 0 and (n == 0 or n_enriched > 0)
    ticker_matching_ready = n_profiles > 0 and n_enriched > 0 and backlog == 0

    return {
        "reg_documents_count": n,
        "enriched_count": n_enriched,
        "raw_pending_count": n_raw,
        "processing_count": n_processing,
        "error_count": n_err,
        "last_document_ingested_at": last_ingest.isoformat() if last_ingest else None,
        "last_enrichment_at": last_enrichment.isoformat() if last_enrichment else None,
        "company_profiles_count": n_profiles,
        "anthropic_configured": anthropic_ok,
        "enrichment_coverage_percent": coverage,
        "enrichment_pipeline_ok": enrichment_pipeline_ok,
        "ticker_matching_ready": ticker_matching_ready,
        "warnings": warnings,
        "message": "Ingest (Federal Register) → enrich (Claude) → match tickers via company_reg_profiles.",
    }


async def _fetch_enriched_rows_since(
    session: AsyncSession,
    since: dt.date,
) -> list[tuple[RegDocument, RegEnrichment, set[str], set[str]]]:
    """All enriched FR documents on or after `since`, with product/function tag sets for matching."""
    rows = (
        await session.execute(
            select(RegDocument, RegEnrichment)
            .join(RegEnrichment, RegEnrichment.document_id == RegDocument.id)
            .where(RegDocument.publication_date >= since)
            .order_by(RegDocument.publication_date.desc())
        )
    ).all()
    out: list[tuple[RegDocument, RegEnrichment, set[str], set[str]]] = []
    for d, e in rows:
        ap = set(json.loads(e.affected_products or "[]"))
        af = set(json.loads(e.affected_functions or "[]"))
        out.append((d, e, ap, af))
    return out


def _impact_payload_for_profile(
    profile: CompanyRegProfile,
    prepared_rows: list[tuple[RegDocument, RegEnrichment, set[str], set[str]]],
    lookback_days: int,
) -> dict[str, Any]:
    products = set(json.loads(profile.primary_products or "[]"))
    functions = set(json.loads(profile.primary_functions or "[]"))
    t = profile.ticker
    matched: list[dict[str, Any]] = []
    for d, e, ap, af in prepared_rows:
        if (ap & products) or (af & functions):
            matched.append(_doc_to_dict(d, e))
    return {
        "ticker": t,
        "company_name": profile.name,
        "lookback_days": lookback_days,
        "profile_products": sorted(products),
        "profile_functions": sorted(functions),
        "matches": matched,
        "note": None
        if matched
        else "No enriched documents matched yet. Run the LLM enrichment pipeline to tag products/functions.",
    }


async def impact_by_ticker(
    session: AsyncSession,
    ticker: str,
    *,
    lookback_days: int = 90,
) -> dict[str, Any] | None:
    """Regulatory items overlapping the company's mapped product/function tags (requires enrichments)."""
    t = ticker.strip().upper()
    profile = await session.get(CompanyRegProfile, t)
    if profile is None:
        return None
    since = dt.date.today() - dt.timedelta(days=max(lookback_days, 1))
    prepared = await _fetch_enriched_rows_since(session, since)
    return _impact_payload_for_profile(profile, prepared, lookback_days)


async def impact_by_tickers_batch(
    session: AsyncSession,
    tickers: list[str],
    *,
    lookback_days: int = 90,
) -> dict[str, Any]:
    """Match many tickers with one query for enriched documents; `by_ticker[t]` is null when no profile exists."""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in tickers:
        u = raw.strip().upper()
        if not u or u in seen:
            continue
        seen.add(u)
        ordered.append(u)

    if not ordered:
        return {"lookback_days": lookback_days, "by_ticker": {}}

    since = dt.date.today() - dt.timedelta(days=max(lookback_days, 1))
    prepared = await _fetch_enriched_rows_since(session, since)

    res = await session.execute(select(CompanyRegProfile).where(CompanyRegProfile.ticker.in_(ordered)))
    profiles = {p.ticker: p for p in res.scalars().all()}

    by_ticker: dict[str, dict[str, Any] | None] = {}
    for tk in ordered:
        p = profiles.get(tk)
        if p is None:
            by_ticker[tk] = None
        else:
            by_ticker[tk] = _impact_payload_for_profile(p, prepared, lookback_days)

    return {"lookback_days": lookback_days, "by_ticker": by_ticker}
