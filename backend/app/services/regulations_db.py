"""SQLite FTS5 setup for regulatory full-text search (populated after LLM enrichment)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS reg_search_fts USING fts5(
    document_id UNINDEXED,
    search_text,
    tokenize = 'porter'
);
"""


async def ensure_reg_search_fts(conn: AsyncConnection) -> None:
    await conn.execute(text(FTS_CREATE_SQL))


async def fts_delete_for_document(conn: AsyncConnection, document_id: str) -> None:
    await conn.execute(text("DELETE FROM reg_search_fts WHERE document_id = :did"), {"did": document_id})


async def fts_insert(conn: AsyncConnection, document_id: str, search_blob: str) -> None:
    await conn.execute(
        text("INSERT INTO reg_search_fts (document_id, search_text) VALUES (:did, :txt)"),
        {"did": document_id, "txt": search_blob},
    )


async def fts_replace_for_document(session: AsyncSession, document_id: str, search_blob: str) -> None:
    await session.execute(text("DELETE FROM reg_search_fts WHERE document_id = :did"), {"did": document_id})
    await session.execute(
        text("INSERT INTO reg_search_fts (document_id, search_text) VALUES (:did, :txt)"),
        {"did": document_id, "txt": search_blob},
    )
