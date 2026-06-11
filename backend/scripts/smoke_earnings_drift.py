from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_QUESTION = "How has MSFT AI narrative drifted over the last several earnings calls?"


def _base_url() -> str:
    raw = os.environ.get("BACKEND_URL") or os.environ.get("NEXT_PUBLIC_BACKEND_URL") or "http://localhost:8000"
    return raw.rstrip("/")


def _token() -> str:
    token = os.environ.get("API_BEARER_TOKEN") or os.environ.get("NEXT_PUBLIC_API_BEARER_TOKEN")
    if not token:
        raise SystemExit("Set API_BEARER_TOKEN or NEXT_PUBLIC_API_BEARER_TOKEN before running this smoke test.")
    return token


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        data = ""
        for line in block.splitlines():
            if line.startswith("data:"):
                data += line.removeprefix("data:").strip()
        if not data:
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def main() -> int:
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION
    payload = json.dumps({"question": question, "context": None}).encode("utf-8")
    req = urllib.request.Request(
        f"{_base_url()}/api/ask/stream",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Earnings Drift smoke test failed: HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Earnings Drift smoke test failed: {e}") from e

    events = _parse_sse_events(raw)
    agents = {str(e.get("agent")) for e in events if e.get("type") in {"agent_start", "agent_end"}}
    answers = [e for e in events if e.get("type") == "answer"]
    run_ends = [e for e in events if e.get("type") == "run_end"]

    failures: list[str] = []
    for required in ("earnings", "earnings_drift"):
        if required not in agents:
            failures.append(f"missing {required} agent in stream")
    if "regulations" in agents:
        failures.append("unexpected regulations agent in earnings-only drift stream")
    if not answers:
        failures.append("missing answer event")
    else:
        drift = str(answers[-1].get("drift_direction") or "")
        if drift not in {"improving", "worsening", "mixed", "stable", "insufficient_history"}:
            failures.append(f"missing/invalid drift_direction: {drift or '<empty>'}")
    if not run_ends or str(run_ends[-1].get("status")) not in {"ok", "partial"}:
        failures.append("missing successful run_end event")

    if failures:
        print("Earnings Drift smoke test FAILED")
        for failure in failures:
            print(f"- {failure}")
        print(f"Observed agents: {sorted(a for a in agents if a and a != 'None')}")
        print(f"Event count: {len(events)}")
        return 1

    print("Earnings Drift smoke test passed")
    print(f"Question: {question}")
    print(f"Direction: {answers[-1].get('drift_direction')} ({answers[-1].get('confidence', 'unknown')} confidence)")
    print(f"Agents: {', '.join(sorted(a for a in agents if a and a != 'None'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
