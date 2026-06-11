"""Daily customer-discovery crawler loop."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from app.db import session_context
from app.market_research.service import generate_daily_brief
from app.settings import settings

logger = logging.getLogger(__name__)


def _seconds_until_next_run() -> float:
    now = dt.datetime.now()
    run_at = now.replace(
        hour=settings.market_research_scheduler_hour,
        minute=settings.market_research_scheduler_minute,
        second=0,
        microsecond=0,
    )
    if run_at <= now:
        run_at += dt.timedelta(days=1)
    return max(1.0, (run_at - now).total_seconds())


async def run_market_research_once() -> dict:
    async with session_context() as session:
        return await generate_daily_brief(session)


async def market_research_scheduler_loop() -> None:
    logger.info(
        "market_research_scheduler_start run_on_startup=%s daily_time=%02d:%02d lookback_hours=%s max_items=%s",
        settings.market_research_scheduler_run_on_startup,
        settings.market_research_scheduler_hour,
        settings.market_research_scheduler_minute,
        settings.market_research_lookback_hours,
        settings.market_research_max_items,
    )

    if settings.market_research_scheduler_run_on_startup:
        try:
            await run_market_research_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("market_research_scheduler_initial_run_failed")

    while True:
        await asyncio.sleep(_seconds_until_next_run())
        try:
            await run_market_research_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("market_research_scheduler_tick_failed")
