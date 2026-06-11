from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ask.orchestrator import build_plan, parse_intent, should_run_regulations


def _assert_claim_check() -> None:
    question = "Claim check: is JPM exposed to new capital rules?"
    intent = parse_intent(question, None)
    assert intent["is_claim_check"] is True
    assert intent["tickers"] == ["JPM"]
    assert intent["needs_earnings"] is True
    assert should_run_regulations(question, intent) is True

    plan = build_plan(intent, run_regulations=True)
    steps = plan["steps"]
    assert steps[-1]["id"] == "claim_check"
    assert steps[-1]["agent"] == "claim_check"
    assert any(step["agent"] == "earnings" for step in steps)
    assert any(step["agent"] == "regulations" for step in steps)


def _assert_earnings_drift() -> None:
    question = "How has MSFT AI narrative drifted over the last several earnings calls?"
    intent = parse_intent(question, None)
    assert intent["is_earnings_drift"] is True
    assert intent["tickers"] == ["MSFT"]
    assert intent["needs_earnings"] is True
    assert should_run_regulations(question, intent) is False

    plan = build_plan(intent, run_regulations=False)
    steps = plan["steps"]
    assert steps[-1]["id"] == "earnings_drift"
    assert steps[-1]["agent"] == "earnings_drift"
    assert any(step["agent"] == "earnings" for step in steps)
    assert any(step["agent"] == "regulations" and step["status"] == "skipped" for step in steps)


def main() -> int:
    _assert_claim_check()
    _assert_earnings_drift()
    print("agent routing checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
