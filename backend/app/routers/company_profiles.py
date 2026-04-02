from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import get_session
from app.models import CompanyRegProfile
from app.schemas import CompanyRegProfilePatch, CompanyRegProfilePut

router = APIRouter(prefix="/api/companies", tags=["company-profiles"])


def _normalize_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if not t or len(t) > 16:
        raise HTTPException(status_code=422, detail="Ticker must be 1–16 characters")
    return t


def _profile_to_dict(p: CompanyRegProfile) -> dict[str, Any]:
    return {
        "ticker": p.ticker,
        "name": p.name,
        "institution_types": json.loads(p.institution_types or "[]"),
        "primary_products": json.loads(p.primary_products or "[]"),
        "primary_functions": json.loads(p.primary_functions or "[]"),
        "gics_sector": p.gics_sector,
        "gics_sub_industry": p.gics_sub_industry,
        "is_auto_generated": p.is_auto_generated,
    }


@router.get("", dependencies=[Depends(require_bearer_token)])
async def list_company_profiles(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    res = await session.execute(select(CompanyRegProfile).order_by(CompanyRegProfile.ticker))
    rows = list(res.scalars().all())
    return [_profile_to_dict(p) for p in rows]


@router.get("/{ticker}", dependencies=[Depends(require_bearer_token)])
async def get_company_profile(ticker: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    p = await session.get(CompanyRegProfile, _normalize_ticker(ticker))
    if p is None:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return _profile_to_dict(p)


@router.put("/{ticker}", dependencies=[Depends(require_bearer_token)])
async def put_company_profile(
    ticker: str,
    body: CompanyRegProfilePut,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create or fully replace a regulatory company profile (used for ticker ↔ FR matching)."""
    t = _normalize_ticker(ticker)
    p = await session.get(CompanyRegProfile, t)
    if p is None:
        p = CompanyRegProfile(ticker=t)
        session.add(p)
    p.name = body.name
    p.institution_types = json.dumps(body.institution_types)
    p.primary_products = json.dumps(body.primary_products)
    p.primary_functions = json.dumps(body.primary_functions)
    p.gics_sector = body.gics_sector
    p.gics_sub_industry = body.gics_sub_industry
    p.is_auto_generated = body.is_auto_generated
    await session.commit()
    await session.refresh(p)
    return _profile_to_dict(p)


@router.patch("/{ticker}", dependencies=[Depends(require_bearer_token)])
async def patch_company_profile(
    ticker: str,
    body: CompanyRegProfilePatch,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update only fields provided in the body."""
    t = _normalize_ticker(ticker)
    p = await session.get(CompanyRegProfile, t)
    if p is None:
        raise HTTPException(status_code=404, detail="Company profile not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        p.name = data["name"]
    if "institution_types" in data:
        p.institution_types = json.dumps(data["institution_types"])
    if "primary_products" in data:
        p.primary_products = json.dumps(data["primary_products"])
    if "primary_functions" in data:
        p.primary_functions = json.dumps(data["primary_functions"])
    if "gics_sector" in data:
        p.gics_sector = data["gics_sector"]
    if "gics_sub_industry" in data:
        p.gics_sub_industry = data["gics_sub_industry"]
    if "is_auto_generated" in data:
        p.is_auto_generated = bool(data["is_auto_generated"])
    await session.commit()
    await session.refresh(p)
    return _profile_to_dict(p)


@router.delete("/{ticker}", status_code=204, dependencies=[Depends(require_bearer_token)])
async def delete_company_profile(ticker: str, session: AsyncSession = Depends(get_session)) -> Response:
    """Remove a company profile. Ticker impact endpoints will 404 until a profile is created again."""
    t = _normalize_ticker(ticker)
    p = await session.get(CompanyRegProfile, t)
    if p is None:
        raise HTTPException(status_code=404, detail="Company profile not found")
    await session.delete(p)
    await session.commit()
    return Response(status_code=204)
