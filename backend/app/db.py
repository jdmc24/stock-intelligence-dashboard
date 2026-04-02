from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.settings import settings


def create_engine() -> AsyncEngine:
    _ensure_sqlite_dir(settings.database_url)
    return create_async_engine(
        settings.database_url,
        future=True,
        echo=False,
    )


def _ensure_sqlite_dir(database_url: str) -> None:
    # Handles sqlite urls like:
    # - sqlite+aiosqlite:///./data/app.db
    # - sqlite:///./data/app.db
    if not database_url.startswith("sqlite"):
        return
    m = database_url.split("///", 1)
    if len(m) != 2:
        return
    path_part = m[1]
    if path_part.startswith(":memory:"):
        return
    db_path = Path(path_part)
    if not db_path.is_absolute():
        # Interpret relative to backend working directory (where uvicorn will run)
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


engine = create_engine()
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_session():
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_context():
    async with SessionLocal() as session:
        yield session

