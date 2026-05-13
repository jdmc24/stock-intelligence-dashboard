"""Deterministic scoring functions for the regulatory enrichment eval.

Each scorer takes the enrichment output (and tool-call trace) plus an
`expected` block from a fixture, and returns `(check_name, passed, message)`.

These are intentionally simple: substring matches, set membership, list
overlap. We do not use LLM-as-judge here — the value of this harness is
that scores are reproducible across runs and free to compute.
"""

from __future__ import annotations

from typing import Any


CheckResult = tuple[str, bool, str]


def _truncate(s: str, n: int = 80) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def check_schema_keys(enrichment: dict[str, Any], required: list[str]) -> CheckResult:
    missing = [k for k in required if k not in enrichment or enrichment.get(k) is None]
    if missing:
        return ("schema_keys_present", False, f"missing keys: {missing}")
    return ("schema_keys_present", True, "all required keys present")


def check_severity_in(enrichment: dict[str, Any], allowed: list[str]) -> CheckResult:
    sev = str(enrichment.get("severity") or "")
    if sev in allowed:
        return ("severity_in_allowed", True, f"severity={sev} in {allowed}")
    return ("severity_in_allowed", False, f"severity={sev or '(empty)'} not in {allowed}")


def check_change_type_in(enrichment: dict[str, Any], allowed: list[str]) -> CheckResult:
    ct = str(enrichment.get("change_type") or "")
    if ct in allowed:
        return ("change_type_in_allowed", True, f"change_type={ct} in {allowed}")
    return ("change_type_in_allowed", False, f"change_type={ct or '(empty)'} not in {allowed}")


def check_list_overlap(
    enrichment: dict[str, Any], field: str, any_of: list[str]
) -> CheckResult:
    actual = enrichment.get(field) or []
    if not isinstance(actual, list):
        return (f"{field}_any_of", False, f"{field} is not a list: {type(actual).__name__}")
    overlap = sorted(set(actual) & set(any_of))
    if overlap:
        return (f"{field}_any_of", True, f"{field} contains {overlap}")
    return (
        f"{field}_any_of",
        False,
        f"{field}={actual or '[]'} does not overlap {any_of}",
    )


def check_summary_contains_any(enrichment: dict[str, Any], words_ci: list[str]) -> CheckResult:
    summary = str(enrichment.get("summary") or "").lower()
    hits = [w for w in words_ci if w.lower() in summary]
    if hits:
        return ("summary_contains_any", True, f"summary mentions {hits[:3]}")
    return (
        "summary_contains_any",
        False,
        f"summary missing any of {words_ci}; got: {_truncate(summary)}",
    )


def check_summary_min_words(enrichment: dict[str, Any], min_words: int) -> CheckResult:
    summary = str(enrichment.get("summary") or "")
    n = len(summary.split())
    if n >= min_words:
        return ("summary_min_words", True, f"{n} words >= {min_words}")
    return ("summary_min_words", False, f"{n} words < {min_words}")


def check_must_call_tool(tool_calls: list[dict[str, Any]], tool_name: str) -> CheckResult:
    names = [tc.get("name") for tc in tool_calls]
    if tool_name in names:
        return (f"called_{tool_name}", True, f"called {tool_name} {names.count(tool_name)}x")
    return (
        f"called_{tool_name}",
        False,
        f"never called {tool_name}; called: {names or 'no tools'}",
    )


def check_reflection_entry(tool_calls: list[dict[str, Any]]) -> CheckResult:
    has = any(tc.get("name") == "self_reflection" for tc in tool_calls)
    if has:
        return ("reflection_entry_present", True, "self_reflection entry found in trace")
    return (
        "reflection_entry_present",
        False,
        "no self_reflection entry in trace — reflection pass not wired or skipped",
    )


def score_fixture(
    expected: dict[str, Any],
    enrichment: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> list[CheckResult]:
    """Run all applicable checks for a fixture's `expected` block.

    Missing keys in `expected` are skipped (not failed) — fixtures opt in
    to the checks they care about.
    """
    results: list[CheckResult] = []

    if "schema_required_keys" in expected:
        results.append(check_schema_keys(enrichment, expected["schema_required_keys"]))

    if "severity_in" in expected:
        results.append(check_severity_in(enrichment, expected["severity_in"]))

    if "change_type_in" in expected:
        results.append(check_change_type_in(enrichment, expected["change_type_in"]))

    for field_key, field_name in (
        ("products_any_of", "affected_products"),
        ("functions_any_of", "affected_functions"),
        ("institution_types_any_of", "institution_types"),
    ):
        if field_key in expected:
            results.append(check_list_overlap(enrichment, field_name, expected[field_key]))

    if "summary_includes_any_of_ci" in expected:
        results.append(check_summary_contains_any(enrichment, expected["summary_includes_any_of_ci"]))

    if "summary_min_words" in expected:
        results.append(check_summary_min_words(enrichment, expected["summary_min_words"]))

    if "must_call_tool" in expected:
        results.append(check_must_call_tool(tool_calls, expected["must_call_tool"]))

    if expected.get("must_have_reflection_entry"):
        results.append(check_reflection_entry(tool_calls))

    return results
