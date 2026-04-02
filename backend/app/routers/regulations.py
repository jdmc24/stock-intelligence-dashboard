from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import get_session
from app.services.regulations_enrichment import enrich_pending_documents, reprocess_document
from app.schemas import RegulatoryImpactBatchIn
from app.services.regulations_service import (
    get_document,
    impact_by_ticker,
    impact_by_tickers_batch,
    list_documents,
    regulations_status,
    run_federal_register_ingest,
)
from app.settings import settings

router = APIRouter(prefix="/api/regulations", tags=["regulations"])


@router.get("/status", dependencies=[Depends(require_bearer_token)])
async def get_regulations_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Pipeline snapshot: document counts by status, timestamps, company profile count, and actionable warnings."""
    return await regulations_status(session)


@router.get("/documents", dependencies=[Depends(require_bearer_token)])
async def get_documents(
    session: AsyncSession = Depends(get_session),
    agency: str | None = None,
    doc_type: str | None = Query(None, alias="type", description="Document type filter (e.g. Notice, Rule)"),
    search: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    items, total = await list_documents(
        session,
        agency_substring=agency,
        doc_type=doc_type,
        search=search,
        page=page,
        per_page=per_page,
    )
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/documents/{doc_id}", dependencies=[Depends(require_bearer_token)])
async def get_reg_document(doc_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    doc = await get_document(session, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/ingest/trigger", dependencies=[Depends(require_bearer_token)])
async def trigger_ingest(
    session: AsyncSession = Depends(get_session),
    days: int = Query(1, ge=1, le=30, description="Publication date window (last N days)"),
) -> dict[str, Any]:
    result = await run_federal_register_ingest(session, days=days)
    return {
        "ok": True,
        "pages_fetched": result.pages_fetched,
        "candidates": result.candidates,
        "inserted": result.inserted,
        "skipped_existing": result.skipped_existing,
        "errors": result.errors,
        "date_start": result.date_start.isoformat(),
        "date_end": result.date_end.isoformat(),
    }


@router.post("/enrich/trigger", dependencies=[Depends(require_bearer_token)])
async def trigger_enrichment(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(5, ge=1, le=25, description="Max raw documents to enrich"),
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")
    try:
        return await enrich_pending_documents(session, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/reprocess/{doc_id}", dependencies=[Depends(require_bearer_token)])
async def trigger_reprocess(doc_id: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")
    try:
        return await reprocess_document(session, doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/impact/batch", dependencies=[Depends(require_bearer_token)])
async def post_impact_batch(
    body: RegulatoryImpactBatchIn,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Match multiple tickers with one enriched-document query; missing profiles return null in by_ticker."""
    return await impact_by_tickers_batch(session, body.tickers, lookback_days=body.lookback_days)


@router.get("/impact/batch", dependencies=[Depends(require_bearer_token)])
async def get_impact_batch(
    session: AsyncSession = Depends(get_session),
    tickers: str = Query(
        ...,
        min_length=1,
        description="Comma-separated tickers, e.g. AAPL,MSFT,JPM",
    ),
    lookback_days: int = Query(90, ge=1, le=365),
) -> dict[str, Any]:
    """Same as POST /impact/batch; convenient for curl and small lists."""
    parts = [p.strip().upper() for p in tickers.split(",") if p.strip()][:50]
    if not parts:
        raise HTTPException(status_code=422, detail="No valid tickers in list")
    return await impact_by_tickers_batch(session, parts, lookback_days=lookback_days)


@router.get("/impact/by-ticker/{ticker}", dependencies=[Depends(require_bearer_token)])
async def get_impact_by_ticker(
    ticker: str,
    session: AsyncSession = Depends(get_session),
    lookback_days: int = Query(90, ge=1, le=365),
) -> dict[str, Any]:
    data = await impact_by_ticker(session, ticker, lookback_days=lookback_days)
    if data is None:
        raise HTTPException(status_code=404, detail="Unknown ticker — add a company profile first")
    return data
