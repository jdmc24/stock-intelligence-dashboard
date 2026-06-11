from __future__ import annotations

import json

from app.settings import settings


_JSON_RETRY_USER = (
    "Your previous reply was not valid JSON. Respond with ONLY one JSON object matching the "
    "requested schema. No markdown fences, no commentary, no text before or after the object."
)


def _parse_model_json(text: str) -> dict:
    from app.services.json_extract import parse_json_object

    return parse_json_object(text)


def _extract_text(resp: object) -> str:
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text

    chunks: list[str] = []
    for item in getattr(resp, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            value = getattr(content, "text", None)
            if isinstance(value, str):
                chunks.append(value)
    return "".join(chunks)


def _usage_tokens(resp: object) -> tuple[int, int]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return 0, 0
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    return input_tokens, output_tokens


def complete_json_with_usage(system: str, user: str, max_tokens: int = 4096) -> tuple[dict, int, int]:
    """Return (parsed_json, input_tokens, output_tokens) using OpenAI Responses API."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    in_total = 0
    out_total = 0
    last_text = ""

    for attempt in range(2):
        resp = client.responses.create(
            model=settings.openai_model,
            input=messages,
            max_output_tokens=max_tokens,
            text={"format": {"type": "json_object"}},
        )
        in_t, out_t = _usage_tokens(resp)
        in_total += in_t
        out_total += out_t
        last_text = _extract_text(resp)
        try:
            return _parse_model_json(last_text), in_total, out_total
        except ValueError:
            if attempt == 0:
                messages.append({"role": "assistant", "content": last_text or json.dumps({"error": "empty"})})
                messages.append({"role": "user", "content": _JSON_RETRY_USER})
                continue
            raise

    raise ValueError("No JSON object found in model output")
