from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _base_url() -> str:
    raw = os.environ.get("BACKEND_URL") or os.environ.get("NEXT_PUBLIC_BACKEND_URL") or "http://localhost:8000"
    return raw.rstrip("/")


def _token() -> str:
    token = os.environ.get("API_BEARER_TOKEN") or os.environ.get("NEXT_PUBLIC_API_BEARER_TOKEN")
    if not token:
        raise SystemExit("Set API_BEARER_TOKEN or NEXT_PUBLIC_API_BEARER_TOKEN before running this smoke test.")
    return token


def _request(path: str, *, method: str = "GET") -> dict[str, Any]:
    req = urllib.request.Request(
        f"{_base_url()}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Market Research smoke test failed: HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Market Research smoke test failed: {e}") from e


def main() -> int:
    trigger = "--trigger" in sys.argv
    status = _request("/api/market-research/status")
    failures: list[str] = []

    for key in ("items", "insights", "briefs", "scheduler_enabled", "rss_feed_count"):
        if key not in status:
            failures.append(f"status missing {key}")

    generated: dict[str, Any] | None = None
    if trigger:
        params = urllib.parse.urlencode({"lookback_hours": 24, "max_items": 40})
        generated = _request(f"/api/market-research/briefs/trigger?{params}", method="POST")
        if generated.get("ok") is not True:
            failures.append("trigger did not return ok=true")
        if int(generated.get("source_item_count") or 0) < 0:
            failures.append("trigger returned invalid source_item_count")

    latest: dict[str, Any] | None = None
    try:
        latest = _request("/api/market-research/briefs/latest")
    except SystemExit as e:
        if trigger:
            raise
        print("Market Research status smoke test passed; no latest brief exists yet.")
        print(f"Status: {status}")
        return 0

    if latest is not None:
        for key in ("title", "markdown", "source_item_count", "insight_count"):
            if key not in latest:
                failures.append(f"latest brief missing {key}")

    if failures:
        print("Market Research smoke test FAILED")
        for failure in failures:
            print(f"- {failure}")
        print(f"Status: {status}")
        if generated is not None:
            print(f"Generated: {generated}")
        return 1

    print("Market Research smoke test passed")
    print(f"Status: {status}")
    if generated is not None:
        print(f"Generated brief: {generated.get('title')}")
    if latest is not None:
        print(f"Latest brief: {latest.get('title')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
