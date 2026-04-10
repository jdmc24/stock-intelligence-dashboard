from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.analysis import router as analysis_router
from app.routers.companies import router as companies_router
from app.routers.company_profiles import router as company_profiles_router
from app.routers.regulations import router as regulations_router
from app.routers.search import router as search_router
from app.routers.transcripts import router as transcripts_router
from app.platform_init import init_company_profiles, init_platform_schema
from app.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.earningcall_api_key:
        import earningscall

        earningscall.api_key = settings.earningcall_api_key
    await init_platform_schema()
    await init_company_profiles()

    scheduler_task: asyncio.Task | None = None
    if settings.regulatory_scheduler_enabled:
        from app.services.regulatory_scheduler import regulatory_scheduler_loop

        scheduler_task = asyncio.create_task(regulatory_scheduler_loop(), name="regulatory_scheduler")
        logger.info("Regulatory scheduler task started (REGULATORY_SCHEDULER_ENABLED=true)")

    yield

    if scheduler_task is not None:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task
        logger.info("Regulatory scheduler task stopped")


app = FastAPI(
    title="Stock Intelligence Dashboard API",
    description="Earnings transcripts, regulatory monitoring (Federal Register), and AI analysis.",
    lifespan=lifespan,
)

# Note: allow_credentials=True with allow_origins=["*"] is invalid per CORS and breaks
# browser fetches from another origin (e.g. :3001 → :8001). We use Bearer tokens, not cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transcripts_router)
app.include_router(analysis_router)
app.include_router(companies_router)
app.include_router(search_router)
app.include_router(regulations_router)
app.include_router(company_profiles_router)


@app.get("/")
async def root():
    """Avoid 404 when someone opens the API base URL in a browser."""
    return {"ok": True, "docs": "/docs", "healthz": "/healthz"}


@app.get("/healthz")
async def healthz():
    return {"ok": True}

