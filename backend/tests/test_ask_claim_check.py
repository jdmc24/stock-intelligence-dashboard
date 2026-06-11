from __future__ import annotations

from app.services.ask.orchestrator import build_plan, parse_intent, should_run_regulations


def test_claim_check_intent_forces_evidence_paths_when_ticker_known():
    intent = parse_intent("Claim check: is JPM exposed to new capital rules?", None)

    assert intent["is_claim_check"] is True
    assert intent["tickers"] == ["JPM"]
    assert intent["needs_earnings"] is True
    assert should_run_regulations("Claim check: is JPM exposed to new capital rules?", intent) is True


def test_claim_check_plan_uses_claim_check_agent_step():
    intent = {
        "tickers": ["JPM"],
        "topics": ["capital"],
        "needs_earnings": True,
        "is_claim_check": True,
    }

    plan = build_plan(intent, run_regulations=True)
    steps = plan["steps"]

    assert steps[-1]["id"] == "claim_check"
    assert steps[-1]["agent"] == "claim_check"
    assert any(step["agent"] == "earnings" for step in steps)
    assert any(step["agent"] == "regulations" for step in steps)


def test_earnings_drift_intent_is_earnings_only():
    question = "How has MSFT's AI narrative drifted over the last several earnings calls?"
    intent = parse_intent(question, None)

    assert intent["is_earnings_drift"] is True
    assert intent["tickers"] == ["MSFT"]
    assert intent["needs_earnings"] is True
    assert should_run_regulations(question, intent) is False


def test_earnings_drift_plan_uses_drift_agent_step():
    intent = {
        "tickers": ["MSFT"],
        "topics": ["AI"],
        "needs_earnings": True,
        "is_claim_check": False,
        "is_earnings_drift": True,
    }

    plan = build_plan(intent, run_regulations=False)
    steps = plan["steps"]

    assert steps[-1]["id"] == "earnings_drift"
    assert steps[-1]["agent"] == "earnings_drift"
    assert any(step["agent"] == "earnings" for step in steps)
    assert any(step["agent"] == "regulations" and step["status"] == "skipped" for step in steps)
