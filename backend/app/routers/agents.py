from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.auth import require_bearer_token
from app.settings import settings

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _agent_status() -> list[dict[str, Any]]:
    llm_ready = bool(settings.anthropic_api_key)
    discovery_llm_ready = bool(settings.openai_api_key)
    return [
        {
            "id": "claim_check",
            "name": "Claim Check Agent",
            "status": "ready",
            "surface": "/ask",
            "sample_prompt": "Claim check: is JPM unusually exposed to new banking capital rules?",
            "uses": ["regulations", "earnings"],
            "requires": {
                "anthropic_api_key": False,
                "full_llm_synthesis": llm_ready,
            },
            "smoke_script": "backend/scripts/smoke_claim_check.py",
            "output_contract": {
                "verdict": ["supported", "mixed", "weakly_supported", "contradicted", "unverifiable"],
                "confidence": ["low", "medium", "high"],
            },
        },
        {
            "id": "earnings_drift",
            "name": "Earnings Narrative Drift Agent",
            "status": "ready",
            "surface": "/ask",
            "sample_prompt": "How has MSFT AI narrative drifted over the last several earnings calls?",
            "uses": ["earnings"],
            "requires": {
                "anthropic_api_key": False,
                "full_llm_synthesis": llm_ready,
            },
            "smoke_script": "backend/scripts/smoke_earnings_drift.py",
            "output_contract": {
                "drift_direction": ["improving", "worsening", "mixed", "stable", "insufficient_history"],
                "confidence": ["low", "medium", "high"],
            },
        },
        {
            "id": "product_discovery",
            "name": "Product Discovery Agent",
            "status": "ready",
            "surface": "/research",
            "sample_prompt": None,
            "uses": ["market_research_sources"],
            "requires": {
                "openai_api_key": False,
                "full_llm_classification": discovery_llm_ready,
            },
            "smoke_script": "backend/scripts/smoke_market_research.py",
            "output_contract": {
                "brief_fields": ["title", "executive_summary", "top_pains", "suggested_experiments", "markdown"],
            },
        },
    ]


@router.get("/status", dependencies=[Depends(require_bearer_token)])
async def get_agents_status() -> dict[str, Any]:
    agents = _agent_status()
    return {
        "ok": True,
        "agent_count": len(agents),
        "agents": agents,
        "suite_smoke_script": "backend/scripts/smoke_agents.py",
        "deployment_blocker": (
            "Deploy from the real Git repo/Railway/Vercel environment, then run the smoke suite against the API."
        ),
    }
