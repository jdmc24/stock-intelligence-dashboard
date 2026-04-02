from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import engine, get_session
from app.models import AnalysisResult, Base, Transcript
from app.schemas import AnalysisOut, CompareIn, ComparisonOut
from app.services.analysis_runner import run_analysis
from app.services.comparison_runner import run_comparison
from app.settings import settings

router = APIRouter(prefix="/api/earnings/analysis", tags=["analysis"])


async def _ensure_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _row_to_out(tid: str, row: AnalysisResult | None) -> AnalysisOut:
    if row is None:
        return AnalysisOut(
            transcript_id=tid,
            status="processing",
            summary=None,
            sentiment=None,
            hedging=None,
            guidance=None,
            topics=None,
            model_used=None,
            created_at=None,
            updated_at=None,
        )
    if row.status == "processing":
        return AnalysisOut(
            transcript_id=tid,
            status="processing",
            error_message=None,
            summary=None,
            sentiment=None,
            hedging=None,
            guidance=None,
            topics=None,
            model_used=None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    if row.status == "error":
        return AnalysisOut(
            transcript_id=tid,
            status="error",
            error_message=row.error_message,
            summary=None,
            sentiment=None,
            hedging=None,
            guidance=None,
            topics=None,
            model_used=row.model_used,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def loads(s: str | None) -> dict | None:
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    return AnalysisOut(
        transcript_id=tid,
        status="complete",
        error_message=None,
        summary=row.summary,
        sentiment=loads(row.sentiment_json),
        hedging=loads(row.hedging_json),
        guidance=loads(row.guidance_json),
        topics=loads(row.topics_json),
        model_used=row.model_used,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/compare", dependencies=[Depends(require_bearer_token)], response_model=ComparisonOut)
async def compare_analysis(body: CompareIn):
    await _ensure_db()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured",
        )
    try:
        result = await run_comparison(body.transcript_ids, body.dimensions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return ComparisonOut(model_used=settings.anthropic_model, comparison=result)


@router.get("/{transcript_id}", dependencies=[Depends(require_bearer_token)], response_model=AnalysisOut)
async def get_analysis(
    transcript_id: str,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    rerun: bool = False,
):
    await _ensure_db()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured",
        )

    t = await session.get(Transcript, transcript_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    if t.status == "processing":
        raise HTTPException(status_code=409, detail="Transcript is still being fetched")

    res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
    row = res.scalar_one_or_none()

    if row and row.status == "complete" and not rerun:
        return _row_to_out(transcript_id, row)

    if row and row.status == "processing":
        return _row_to_out(transcript_id, row)

    if row and row.status == "error" and not rerun:
        return _row_to_out(transcript_id, row)

    if row is None:
        session.add(AnalysisResult(transcript_id=transcript_id, status="processing"))
        await session.commit()
    elif rerun and row.status in ("complete", "error"):
        row.status = "processing"
        row.error_message = None
        row.sentiment_json = None
        row.hedging_json = None
        row.guidance_json = None
        row.topics_json = None
        row.summary = None
        await session.commit()

    background.add_task(run_analysis, transcript_id)
    res2 = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
    row2 = res2.scalar_one_or_none()
    return _row_to_out(transcript_id, row2)


@router.get("/{transcript_id}/sentiment", dependencies=[Depends(require_bearer_token)])
async def get_sentiment(transcript_id: str, session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
    row = res.scalar_one_or_none()
    if row is None or row.status != "complete":
        raise HTTPException(status_code=404, detail="Analysis not ready")
    return json.loads(row.sentiment_json) if row.sentiment_json else {}


@router.get("/{transcript_id}/hedging", dependencies=[Depends(require_bearer_token)])
async def get_hedging(transcript_id: str, session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
    row = res.scalar_one_or_none()
    if row is None or row.status != "complete":
        raise HTTPException(status_code=404, detail="Analysis not ready")
    return json.loads(row.hedging_json) if row.hedging_json else {}


@router.get("/{transcript_id}/guidance", dependencies=[Depends(require_bearer_token)])
async def get_guidance(transcript_id: str, session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
    row = res.scalar_one_or_none()
    if row is None or row.status != "complete":
        raise HTTPException(status_code=404, detail="Analysis not ready")
    return json.loads(row.guidance_json) if row.guidance_json else {}


@router.get("/{transcript_id}/topics", dependencies=[Depends(require_bearer_token)])
async def get_topics(transcript_id: str, session: AsyncSession = Depends(get_session)):
    await _ensure_db()
    res = await session.execute(select(AnalysisResult).where(AnalysisResult.transcript_id == transcript_id))
    row = res.scalar_one_or_none()
    if row is None or row.status != "complete":
        raise HTTPException(status_code=404, detail="Analysis not ready")
    return json.loads(row.topics_json) if row.topics_json else {}
