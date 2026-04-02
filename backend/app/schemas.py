from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


TranscriptStatus = Literal["raw", "processing", "analyzed", "error"]
TranscriptSource = Literal["earningscall", "upload"]
SectionType = Literal["operator_intro", "prepared_remarks", "qa"]


class TranscriptSectionOut(BaseModel):
    id: str
    transcript_id: str
    section_type: SectionType
    speaker: str | None
    text: str
    order: int


class TranscriptOut(BaseModel):
    id: str
    ticker: str
    company_name: str | None = None
    quarter: str | None = None
    call_date: dt.date | None = None
    source: TranscriptSource
    source_url: str | None = None
    raw_text: str
    status: TranscriptStatus
    error_message: str | None = None
    created_at: dt.datetime
    processed_at: dt.datetime | None = None
    sections: list[TranscriptSectionOut] = Field(default_factory=list)


class TranscriptFetchIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    quarter: str | None = Field(default=None, max_length=32)


class TranscriptFetchOut(BaseModel):
    transcript_id: str
    status: TranscriptStatus


class TranscriptUploadIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    quarter: str | None = Field(default=None, max_length=32)
    company_name: str | None = None
    call_date: dt.date | None = None
    raw_text: str = Field(min_length=1)


AnalysisStatus = Literal["processing", "complete", "error"]


class AnalysisOut(BaseModel):
    transcript_id: str
    status: AnalysisStatus
    error_message: str | None = None
    summary: str | None = None
    sentiment: dict[str, Any] | None = None
    hedging: dict[str, Any] | None = None
    guidance: dict[str, Any] | None = None
    topics: dict[str, Any] | None = None
    model_used: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class CompareIn(BaseModel):
    transcript_ids: list[str] = Field(min_length=2)
    dimensions: list[str] | None = None


class ComparisonOut(BaseModel):
    model_used: str
    comparison: dict[str, Any]


class CompanySummary(BaseModel):
    ticker: str
    company_name: str | None = None
    transcript_count: int


class TimelinePoint(BaseModel):
    transcript_id: str
    quarter: str | None = None
    call_date: dt.date | None = None
    overall_tone: str | None = None
    hedging_score: float | None = None
    guidance_count: int = 0
    top_topics: list[str] = Field(default_factory=list)


class CompanyTimelineOut(BaseModel):
    ticker: str
    company_name: str | None = None
    points: list[TimelinePoint]


class SearchHit(BaseModel):
    transcript_id: str
    ticker: str
    quarter: str | None = None
    company_name: str | None = None
    status: TranscriptStatus
    snippet: str


class QuoteHit(BaseModel):
    transcript_id: str
    ticker: str
    quarter: str | None = None
    section_type: SectionType
    speaker: str | None = None
    excerpt: str
    order: int


class RegulatoryImpactBatchIn(BaseModel):
    """POST body for /api/regulations/impact/batch."""

    tickers: list[str] = Field(..., min_length=1, max_length=50)
    lookback_days: int = Field(default=90, ge=1, le=365)


# Must align with LLM enrichment enums (regulations_prompts / enrichment validators).
_INSTITUTION_TYPES = frozenset(
    {"commercial_bank", "credit_union", "mortgage_servicer", "broker_dealer", "fintech", "insurance", "other"}
)


def _validate_institution_types(vals: list[str]) -> list[str]:
    bad = [x for x in vals if x not in _INSTITUTION_TYPES]
    if bad:
        raise ValueError(f"Invalid institution_types {bad}; allowed: {sorted(_INSTITUTION_TYPES)}")
    return vals


def _validate_products(vals: list[str]) -> list[str]:
    from app.prompts.regulations_prompts import CANONICAL_PRODUCTS

    allowed = frozenset(CANONICAL_PRODUCTS)
    bad = [x for x in vals if x not in allowed]
    if bad:
        raise ValueError(f"Invalid primary_products {bad}; allowed: {sorted(allowed)}")
    return vals


def _validate_functions(vals: list[str]) -> list[str]:
    from app.prompts.regulations_prompts import CANONICAL_FUNCTIONS

    allowed = frozenset(CANONICAL_FUNCTIONS)
    bad = [x for x in vals if x not in allowed]
    if bad:
        raise ValueError(f"Invalid primary_functions {bad}; allowed: {sorted(allowed)}")
    return vals


class CompanyRegProfilePut(BaseModel):
    """Full create/replace body for PUT /api/companies/{ticker}."""

    name: str = Field(min_length=1, max_length=256)
    institution_types: list[str] = Field(default_factory=list, max_length=32)
    primary_products: list[str] = Field(default_factory=list, max_length=64)
    primary_functions: list[str] = Field(default_factory=list, max_length=64)
    gics_sector: str | None = Field(default=None, max_length=128)
    gics_sub_industry: str | None = Field(default=None, max_length=256)
    is_auto_generated: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("institution_types", mode="before")
    @classmethod
    def check_inst(cls, v: object) -> object:
        if not isinstance(v, list):
            raise TypeError("institution_types must be a list")
        return _validate_institution_types([str(x) for x in v])

    @field_validator("primary_products", mode="before")
    @classmethod
    def check_prod(cls, v: object) -> object:
        if not isinstance(v, list):
            raise TypeError("primary_products must be a list")
        return _validate_products([str(x) for x in v])

    @field_validator("primary_functions", mode="before")
    @classmethod
    def check_fn(cls, v: object) -> object:
        if not isinstance(v, list):
            raise TypeError("primary_functions must be a list")
        return _validate_functions([str(x) for x in v])


class CompanyRegProfilePatch(BaseModel):
    """Partial update for PATCH /api/companies/{ticker}. Omitted fields are unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    institution_types: list[str] | None = None
    primary_products: list[str] | None = None
    primary_functions: list[str] | None = None
    gics_sector: str | None = Field(default=None, max_length=128)
    gics_sub_industry: str | None = Field(default=None, max_length=256)
    is_auto_generated: bool | None = None

    model_config = {"extra": "forbid"}

    @field_validator("institution_types", mode="before")
    @classmethod
    def check_inst(cls, v: object) -> object:
        if v is None:
            return None
        if not isinstance(v, list):
            raise TypeError("institution_types must be a list")
        return _validate_institution_types([str(x) for x in v])

    @field_validator("primary_products", mode="before")
    @classmethod
    def check_prod(cls, v: object) -> object:
        if v is None:
            return None
        if not isinstance(v, list):
            raise TypeError("primary_products must be a list")
        return _validate_products([str(x) for x in v])

    @field_validator("primary_functions", mode="before")
    @classmethod
    def check_fn(cls, v: object) -> object:
        if v is None:
            return None
        if not isinstance(v, list):
            raise TypeError("primary_functions must be a list")
        return _validate_functions([str(x) for x in v])

