from __future__ import annotations

import json
import re


def _balanced_json_objects(text: str) -> list[str]:
    """Return top-level {...} substrings with balanced braces (respects strings)."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        start = i
        for j in range(i, n):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start : j + 1])
                    i = j + 1
                    break
        else:
            break
    return out


def parse_json_object(text: str) -> dict:
    """Extract a single JSON object from model output (strips markdown fences)."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("No JSON object found in model output")

    candidates: list[str] = []

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE):
        block = match.group(1).strip()
        if block:
            candidates.append(block)

    candidates.append(raw)
    candidates.extend(_balanced_json_objects(raw))

    # Legacy slice fallback when braces are unbalanced (truncated output).
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])

    seen: set[str] = set()
    last_err: json.JSONDecodeError | None = None
    for candidate in candidates:
        c = candidate.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            obj = json.loads(c)
        except json.JSONDecodeError as e:
            last_err = e
            continue
        if isinstance(obj, dict):
            return obj

    if last_err is not None:
        raise ValueError(f"No JSON object found in model output: {last_err}") from last_err
    raise ValueError("No JSON object found in model output")
