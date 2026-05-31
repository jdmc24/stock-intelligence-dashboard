from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyRegProfile, Transcript
from app.prompts.company_profile_prompts import AUTO_PROFILE_SYSTEM
from app.schemas import _validate_functions, _validate_institution_types, _validate_products
from app.services.llm.anthropic_client import complete_json_with_usage
from app.settings import settings

logger = logging.getLogger(__name__)


async def _company_name_from_transcripts(session: AsyncSession, ticker: str) -> str | None:
    row = (
        await session.execute(
            select(Transcript.company_name)
            .where(Transcript.ticker == ticker)
            .order_by(Transcript.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if isinstance(row, str) and row.strip():
        return row.strip()
    return None


def _fallback_profile(ticker: str, name: str, context_question: str | None = None) -> dict[str, Any]:
    """Conservative default when LLM is unavailable."""
    q = (context_question or "").lower()
    functions = ["cybersecurity", "privacy", "vendor_management"]
    if any(k in q for k in ("capital", "bank", "lending", "mortgage")):
        functions = ["capital_requirements", "cybersecurity", "privacy"]
    if any(k in q for k in ("payment", "consumer", "card")):
        products = ["payments", "digital_banking"]
    else:
        products = ["digital_banking", "payments"]

    return {
        "name": name,
        "institution_types": ["other"],
        "primary_products": products,
        "primary_functions": functions,
        "gics_sector": None,
        "gics_sub_industry": None,
    }


def _normalize_generated(raw: dict[str, Any], ticker: str, fallback_name: str) -> dict[str, Any]:
    name = str(raw.get("name") or fallback_name or ticker).strip() or ticker
    inst = raw.get("institution_types")
    prods = raw.get("primary_products")
    funcs = raw.get("primary_functions")
    if not isinstance(inst, list):
        inst = ["other"]
    if not isinstance(prods, list):
        prods = ["digital_banking"]
    if not isinstance(funcs, list):
        funcs = ["cybersecurity", "privacy"]

    try:
        inst = _validate_institution_types([str(x) for x in inst])
        prods = _validate_products([str(x) for x in prods])
        funcs = _validate_functions([str(x) for x in funcs])
    except ValueError as e:
        logger.warning("auto profile validation failed for %s: %s — using fallback", ticker, e)
        fb = _fallback_profile(ticker, name)
        return fb

    if not inst:
        inst = ["other"]
    if not prods:
        prods = ["digital_banking"]
    if not funcs:
        funcs = ["cybersecurity", "privacy"]

    gics_sector = raw.get("gics_sector")
    gics_sub = raw.get("gics_sub_industry")
    return {
        "name": name,
        "institution_types": inst,
        "primary_products": prods,
        "primary_functions": funcs,
        "gics_sector": str(gics_sector).strip() if isinstance(gics_sector, str) and gics_sector.strip() else None,
        "gics_sub_industry": str(gics_sub).strip() if isinstance(gics_sub, str) and gics_sub.strip() else None,
    }


async def _generate_profile_payload(
    ticker: str,
    *,
    company_name: str | None,
    context_question: str | None,
) -> dict[str, Any]:
    display = company_name or ticker
    if not settings.anthropic_api_key:
        return _fallback_profile(ticker, display, context_question)

    user = (
        f"Ticker: {ticker}\n"
        f"Known company name (may be empty): {company_name or '(unknown)'}\n"
    )
    if context_question:
        user += f"\nUser question (for thematic hints):\n{context_question.strip()}\n"

    try:
        raw, _in_t, _out_t = await asyncio.to_thread(
            complete_json_with_usage,
            AUTO_PROFILE_SYSTEM,
            user,
            2048,
        )
        if not isinstance(raw, dict):
            raise ValueError("LLM returned non-object")
        return _normalize_generated(raw, ticker, display)
    except Exception as e:
        logger.warning("LLM auto profile failed for %s: %s", ticker, e)
        return _fallback_profile(ticker, display, context_question)


async def ensure_company_reg_profile(
    session: AsyncSession,
    ticker: str,
    *,
    context_question: str | None = None,
    commit: bool = True,
) -> tuple[CompanyRegProfile | None, bool]:
    """Return an existing profile, or create one with is_auto_generated=True.

    Returns (profile, created). profile is None only when ticker is empty/invalid.
    Does not overwrite manual profiles (is_auto_generated=False).
    """
    t = (ticker or "").strip().upper()
    if not t or len(t) > 16:
        return None, False

    existing = await session.get(CompanyRegProfile, t)
    if existing is not None:
        return existing, False

    company_name = await _company_name_from_transcripts(session, t)
    payload = await _generate_profile_payload(t, company_name=company_name, context_question=context_question)

    profile = CompanyRegProfile(
        ticker=t,
        name=payload["name"],
        institution_types=json.dumps(payload["institution_types"]),
        primary_products=json.dumps(payload["primary_products"]),
        primary_functions=json.dumps(payload["primary_functions"]),
        gics_sector=payload.get("gics_sector"),
        gics_sub_industry=payload.get("gics_sub_industry"),
        is_auto_generated=True,
        user_overrides=None,
    )
    session.add(profile)
    if commit:
        await session.commit()
        await session.refresh(profile)
    else:
        await session.flush()
    return profile, True


def profile_to_dict(p: CompanyRegProfile) -> dict[str, Any]:
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
