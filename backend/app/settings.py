from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load backend/.env regardless of where uvicorn was started (cwd).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
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
    earningcall_api_key: str | None = Field(
        default=None,
        validation_alias="EARNINGSCALL_API_KEY",
        description="EarningsCall.biz API key (Basic+ unlocks non–AAPL/MSFT tickers)",
    )
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


settings = Settings()

