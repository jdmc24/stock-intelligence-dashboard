from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import get_session
from app.market_research.service import generate_daily_brief, latest_brief, list_briefs, market_research_status
from app.models import DailyResearchBrief

router = APIRouter(prefix="/api/market-research", tags=["market research"])


def _brief_to_dict(brief: DailyResearchBrief) -> dict[str, Any]:
    return {
        "id": brief.id,
        "brief_date": brief.brief_date.isoformat(),
        "title": brief.title,
        "executive_summary": brief.executive_summary,
        "markdown": brief.markdown,
        "top_pains": json.loads(brief.top_pains_json or "[]"),
        "suggested_experiments": json.loads(brief.suggested_experiments_json or "[]"),
        "source_item_count": brief.source_item_count,
        "insight_count": brief.insight_count,
        "created_at": brief.created_at.isoformat(),
        "updated_at": brief.updated_at.isoformat(),
    }


@router.get("/status", dependencies=[Depends(require_bearer_token)])
async def get_market_research_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await market_research_status(session)


@router.post("/briefs/trigger", dependencies=[Depends(require_bearer_token)])
async def trigger_market_research_brief(
    session: AsyncSession = Depends(get_session),
    lookback_hours: int = Query(24, ge=1, le=168),
    max_items: int = Query(40, ge=5, le=200),
) -> dict[str, Any]:
    return await generate_daily_brief(session, lookback_hours=lookback_hours, max_items=max_items)


@router.get("/briefs/latest", dependencies=[Depends(require_bearer_token)])
async def get_latest_market_research_brief(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    brief = await latest_brief(session)
    if brief is None:
        raise HTTPException(status_code=404, detail="No market research brief has been generated yet")
    return _brief_to_dict(brief)


@router.get("/briefs", dependencies=[Depends(require_bearer_token)])
async def get_market_research_briefs(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    briefs = await list_briefs(session, limit=limit)
    return {"items": [_brief_to_dict(brief) for brief in briefs]}
