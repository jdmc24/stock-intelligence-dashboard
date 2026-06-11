from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load backend/.env when present (local dev). On Railway/Vercel, use process env only.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH if _ENV_PATH.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str | None = None
    # Use a current API id — older ids (e.g. claude-3-5-sonnet-20241022) return 404.
    # Override with ANTHROPIC_MODEL in backend/.env. See https://docs.anthropic.com/en/docs/about-claude/models/overview
    anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        validation_alias="ANTHROPIC_MODEL",
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="OpenAI API key for the daily market research crawler.",
    )
    openai_model: str = Field(
        default="gpt-5.4-mini",
        validation_alias="OPENAI_MODEL",
        description="OpenAI model used by the daily market research crawler.",
    )
    earningcall_api_key: str | None = Field(
        default=None,
        validation_alias="EARNINGSCALL_API_KEY",
        description="EarningsCall.biz API key (Basic+ unlocks non–AAPL/MSFT tickers)",
    )

    @field_validator("earningcall_api_key", mode="before")
    @classmethod
    def strip_earningcall_api_key(cls, v: object) -> str | None:
        """Avoid invalid-key errors from accidental newlines/spaces in Railway/env pastes."""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v  # type: ignore[return-value]

    sec_user_agent: str
    api_bearer_token: str
    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # In-process scheduler (while uvicorn is running). For production you can instead use cron + `python -m app.regulatory_pipeline`.
    regulatory_scheduler_enabled: bool = Field(
        default=False,
        validation_alias="REGULATORY_SCHEDULER_ENABLED",
        description="If true, background task runs FR ingest + enrich on an interval.",
    )
    regulatory_scheduler_interval_minutes: int = Field(
        default=360,
        ge=1,
        validation_alias="REGULATORY_SCHEDULER_INTERVAL_MINUTES",
        description="Sleep between pipeline runs (default 6 hours).",
    )
    regulatory_scheduler_run_on_startup: bool = Field(
        default=True,
        validation_alias="REGULATORY_SCHEDULER_RUN_ON_STARTUP",
        description="Run ingest+enrich once when the API process starts (if scheduler enabled).",
    )
    regulatory_scheduler_ingest_days: int = Field(
        default=3,
        ge=1,
        le=30,
        validation_alias="REGULATORY_SCHEDULER_INGEST_DAYS",
        description="Publication window for Federal Register ingest each tick.",
    )
    regulatory_scheduler_enrich_limit: int = Field(
        default=10,
        ge=1,
        le=25,
        validation_alias="REGULATORY_SCHEDULER_ENRICH_LIMIT",
        description="Max raw documents to enrich per tick (Claude calls).",
    )

    # Daily customer-discovery crawler for market research briefs.
    market_research_scheduler_enabled: bool = Field(
        default=False,
        validation_alias="MARKET_RESEARCH_SCHEDULER_ENABLED",
        description="If true, background task builds a daily customer-discovery brief.",
    )
    market_research_scheduler_run_on_startup: bool = Field(
        default=False,
        validation_alias="MARKET_RESEARCH_SCHEDULER_RUN_ON_STARTUP",
        description="Run the market research crawler once when the API starts.",
    )
    market_research_scheduler_hour: int = Field(
        default=7,
        ge=0,
        le=23,
        validation_alias="MARKET_RESEARCH_SCHEDULER_HOUR",
        description="Local hour for the daily market research brief.",
    )
    market_research_scheduler_minute: int = Field(
        default=30,
        ge=0,
        le=59,
        validation_alias="MARKET_RESEARCH_SCHEDULER_MINUTE",
        description="Local minute for the daily market research brief.",
    )
    market_research_lookback_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        validation_alias="MARKET_RESEARCH_LOOKBACK_HOURS",
        description="Lookback window for source items.",
    )
    market_research_max_items: int = Field(
        default=40,
        ge=5,
        le=200,
        validation_alias="MARKET_RESEARCH_MAX_ITEMS",
        description="Max normalized source items to process per brief.",
    )
    market_research_rss_urls: str = Field(
        default="",
        validation_alias="MARKET_RESEARCH_RSS_URLS",
        description="Comma-separated RSS feed URLs to include in market research crawling.",
    )


settings = Settings()
