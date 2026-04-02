"""Scheduled Federal Register ingest + LLM enrichment (optional in-process loop or CLI)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_context
from app.services.regulations_enrichment import enrich_pending_documents
from app.services.regulations_service import IngestResult, run_federal_register_ingest
from app.settings import settings

logger = logging.getLogger(__name__)


def _ingest_to_dict(r: IngestResult) -> dict[str, Any]:
    return {
        "pages_fetched": r.pages_fetched,
        "candidates": r.candidates,
        "inserted": r.inserted,
        "skipped_existing": r.skipped_existing,
        "errors": r.errors,
        "date_start": r.date_start.isoformat(),
        "date_end": r.date_end.isoformat(),
    }


async def run_regulatory_pipeline_once(
    session: AsyncSession,
    *,
    ingest_days: int | None = None,
    enrich_limit: int | None = None,
) -> dict[str, Any]:
    """
    Pull recent Federal Register documents, then enrich up to `enrich_limit` raw rows.
    Uses one DB session for both steps so new ingest rows are visible to enrichment.
    """
    days = ingest_days if ingest_days is not None else settings.regulatory_scheduler_ingest_days
    lim = enrich_limit if enrich_limit is not None else settings.regulatory_scheduler_enrich_limit

    logger.info(
        "regulatory_pipeline_start ingest_days=%s enrich_limit=%s",
        days,
        lim,
    )
    ingest_result = await run_federal_register_ingest(session, days=days)
    ingest_dict = _ingest_to_dict(ingest_result)
    logger.info(
        "regulatory_pipeline_ingest_done inserted=%s skipped=%s errors=%s pages=%s",
        ingest_result.inserted,
        ingest_result.skipped_existing,
        ingest_result.errors,
        ingest_result.pages_fetched,
    )

    enrich_out: dict[str, Any] | None = None
    if settings.anthropic_api_key and str(settings.anthropic_api_key).strip():
        enrich_out = await enrich_pending_documents(session, limit=lim)
        logger.info(
            "regulatory_pipeline_enrich_done requested=%s succeeded=%s",
            enrich_out.get("requested"),
            enrich_out.get("succeeded"),
        )
    else:
        enrich_out = {"skipped": True, "reason": "ANTHROPIC_API_KEY not set"}
        logger.warning("regulatory_pipeline_enrich_skipped: no ANTHROPIC_API_KEY")

    out: dict[str, Any] = {"ingest": ingest_dict, "enrich": enrich_out}
    if isinstance(enrich_out, dict) and not enrich_out.get("skipped"):
        logger.info(
            "regulatory_pipeline_complete inserted=%s enrich_requested=%s enrich_succeeded=%s",
            ingest_result.inserted,
            enrich_out.get("requested"),
            enrich_out.get("succeeded"),
        )
    else:
        logger.info(
            "regulatory_pipeline_complete inserted=%s enrich=%s",
            ingest_result.inserted,
            enrich_out,
        )
    return out


async def regulatory_scheduler_loop() -> None:
    """Background loop: optional immediate run, then sleep `interval_minutes` between runs."""
    interval_sec = max(1, settings.regulatory_scheduler_interval_minutes) * 60
    logger.info(
        "regulatory_scheduler_loop_start interval_minutes=%s run_on_startup=%s ingest_days=%s enrich_limit=%s",
        settings.regulatory_scheduler_interval_minutes,
        settings.regulatory_scheduler_run_on_startup,
        settings.regulatory_scheduler_ingest_days,
        settings.regulatory_scheduler_enrich_limit,
    )

    if settings.regulatory_scheduler_run_on_startup:
        try:
            async with session_context() as session:
                await run_regulatory_pipeline_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("regulatory_scheduler_initial_run_failed")

    while True:
        await asyncio.sleep(interval_sec)
        try:
            async with session_context() as session:
                await run_regulatory_pipeline_once(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("regulatory_scheduler_tick_failed")


async def run_regulatory_pipeline_cli() -> dict[str, Any]:
    """CLI / cron: ensure schema, seed profiles if empty, run one pipeline pass."""
    from app.platform_init import init_company_profiles, init_platform_schema

    await init_platform_schema()
    await init_company_profiles()
    async with session_context() as session:
        return await run_regulatory_pipeline_once(session)
