from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    company_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    quarter: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    call_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(16))  # earningscall | upload
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    raw_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), index=True)  # raw|processing|analyzed|error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    sections: Mapped[list[TranscriptSection]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )
    analysis: Mapped["AnalysisResult | None"] = relationship(
        back_populates="transcript", uselist=False, cascade="all, delete-orphan"
    )


class TranscriptSection(Base):
    __tablename__ = "transcript_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    transcript_id: Mapped[str] = mapped_column(String(36), ForeignKey("transcripts.id"), index=True)

    section_type: Mapped[str] = mapped_column(String(32))  # operator_intro|prepared_remarks|qa
    speaker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer)

    transcript: Mapped[Transcript] = relationship(back_populates="sections")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id"), unique=True, index=True
    )

    status: Mapped[str] = mapped_column(String(24), index=True)  # processing|complete|error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hedging_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC)
    )

    transcript: Mapped[Transcript] = relationship(back_populates="analysis")


class RegDocument(Base):
    """Federal Register document (ingested raw; enriched in a later pipeline step)."""

    __tablename__ = "reg_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_date: Mapped[dt.date] = mapped_column(Date, index=True)
    document_type: Mapped[str] = mapped_column(String(64), index=True)

    agencies: Mapped[str] = mapped_column(Text)  # JSON list of display names or slugs
    federal_register_url: Mapped[str] = mapped_column(String(2048))
    pdf_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    cfr_references: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    fr_topics: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list

    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="raw")  # raw|processing|enriched|error

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC)
    )

    enrichment: Mapped["RegEnrichment | None"] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )


class RegEnrichment(Base):
    __tablename__ = "reg_enrichments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("reg_documents.id"), unique=True, index=True)

    summary: Mapped[str] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(64))
    effective_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    comment_deadline: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    compliance_deadline: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_final: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    affected_products: Mapped[str] = mapped_column(Text)  # JSON list
    affected_functions: Mapped[str] = mapped_column(Text)  # JSON list
    institution_types: Mapped[str] = mapped_column(Text)  # JSON list
    severity: Mapped[str] = mapped_column(String(24), index=True)
    severity_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    provisions: Mapped[str] = mapped_column(Text)  # JSON list of objects
    action_items: Mapped[str | None] = mapped_column(Text, nullable=True)

    model_used: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    processing_cost_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))

    document: Mapped[RegDocument] = relationship(back_populates="enrichment")


class RegDigest(Base):
    __tablename__ = "reg_digests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    digest_date: Mapped[dt.date] = mapped_column(Date, unique=True, index=True)
    total_documents: Mapped[int] = mapped_column(Integer)
    high_severity_count: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)  # JSON
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))


class CompanyRegProfile(Base):
    """Ticker → regulatory product/function tags (V1 seeded from JSON)."""

    __tablename__ = "company_reg_profiles"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    institution_types: Mapped[str] = mapped_column(Text)
    primary_products: Mapped[str] = mapped_column(Text)
    primary_functions: Mapped[str] = mapped_column(Text)
    gics_sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gics_sub_industry: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    user_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC)
    )

