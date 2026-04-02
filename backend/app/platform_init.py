"""One-time DB setup: ORM tables + regulatory FTS virtual table + company profile seed."""

from __future__ import annotations

import app.models  # noqa: F401 — register models with Base.metadata

from app.db import SessionLocal, engine
from app.models import Base
from app.services.regulations_db import ensure_reg_search_fts
from app.services.regulations_service import seed_company_profiles


async def init_platform_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_reg_search_fts(conn)


async def init_company_profiles() -> None:
    async with SessionLocal() as session:
        await seed_company_profiles(session)
