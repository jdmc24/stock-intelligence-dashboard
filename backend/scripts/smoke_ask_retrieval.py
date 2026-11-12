from __future__ import annotations

import json
import urllib.request

from smoke_earnings_drift import _base_url, _parse_sse_events, _token


def ask(question: str) -> list[dict]:
    request = urllib.request.Request(
        f"{_base_url()}/api/ask/stream",
        data=json.dumps({"question": question}).encode(),
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        events = _parse_sse_events(response.read().decode())
    if not events or events[-1].get("type") != "run_end" or events[-1].get("status") not in {"ok", "partial"}:
        raise SystemExit(f"Ask did not complete for {question!r}. Check the Railway runtime logs.")
    return events


def verify(
    question: str, tickers: list[str], *, require_transcript: bool = False, overview: bool = False
) -> None:
    events = ask(question)
    plan = next(event for event in events if event.get("type") == "plan")
    answer = next(event for event in events if event.get("type") == "answer")
    assert plan["intent"]["tickers"] == tickers, (question, plan["intent"]["tickers"])
    results = [
        event for event in events
        if event.get("type") == "tool_end" and event.get("tool") == "retrieve_earnings_transcripts"
    ]
    assert [event["input"]["ticker"] for event in results] == tickers
    assert all(event["seq"] < answer["seq"] for event in results)
    ids = {tid for event in results for tid in event["output"]["transcript_ids"]}
    citations = {c["id"] for c in answer["citations"] if c["kind"] == "transcript"}
    if ids or require_transcript:
        assert ids and ids == citations, (question, "Missing a retrieved transcript citation")
    elif tickers:
        assert not results[0]["is_error"], (question, "Transcript provider failed")
        assert not citations and any("transcript was available" in gap for gap in answer["limitations"]), question
    if overview:
        read = next(event for event in events if event.get("tool") == "read_earnings_transcripts"
                    and event["type"] == "tool_end")
        assert not read["input"]["topic"] and read["output"]["count"] >= 3, "Missing call overview passages"
        assert events[-1]["status"] == "ok", "Overview reported an evidence gap"
    print(f"PASS {question} ({len(ids)} retrieved transcript(s))")


if __name__ == "__main__":
    verify("What did MSFT say on its last earnings call?", ["MSFT"], require_transcript=True)
    verify("What did ferrari say on its last earnings call?", ["RACE"])
    verify("tell me about the latest earnings call for eli lilly. what did the c-suite talk about?",
           ["LLY"], require_transcript=True, overview=True)
    verify("Summarize high-severity banking regulations from the last 90 days.", [])
