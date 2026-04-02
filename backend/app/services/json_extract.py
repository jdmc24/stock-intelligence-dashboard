from __future__ import annotations

import json
import re


def parse_json_object(text: str) -> dict:
    """Extract a single JSON object from model output (strips markdown fences)."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if fence:
        t = fence.group(1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(t[start : end + 1])
