from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def _run(label: str, args: list[str]) -> int:
    print(f"\n== {label} ==")
    proc = subprocess.run([sys.executable, *args], cwd=SCRIPT_DIR.parent)
    if proc.returncode == 0:
        print(f"{label}: ok")
    else:
        print(f"{label}: failed ({proc.returncode})")
    return proc.returncode


def main() -> int:
    trigger_market_research = "--trigger-market-research" in sys.argv

    checks = [
        ("Claim Check Agent", ["scripts/smoke_claim_check.py"]),
        ("Earnings Drift Agent", ["scripts/smoke_earnings_drift.py"]),
        (
            "Product Discovery Agent",
            [
                "scripts/smoke_market_research.py",
                *(["--trigger"] if trigger_market_research else []),
            ],
        ),
    ]

    failures = 0
    for label, args in checks:
        failures += 1 if _run(label, args) != 0 else 0

    if failures:
        print(f"\nAgent smoke suite failed: {failures} check(s) failed.")
        return 1

    print("\nAgent smoke suite passed.")
    if not trigger_market_research:
        print("Product Discovery Agent was checked in status-only mode. Add --trigger-market-research to generate a fresh brief.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
