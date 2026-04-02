from __future__ import annotations

from anthropic import Anthropic

from app.settings import settings


def get_client() -> Anthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=settings.anthropic_api_key)


def complete_json(system: str, user: str, max_tokens: int = 8192) -> dict:
    data, _in_t, _out_t = complete_json_with_usage(system, user, max_tokens=max_tokens)
    return data


def complete_json_with_usage(system: str, user: str, max_tokens: int = 8192) -> tuple[dict, int, int]:
    """Returns (parsed_json, input_tokens, output_tokens)."""
    client = get_client()
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = ""
    for block in msg.content:
        if block.type == "text":
            text += block.text
    from app.services.json_extract import parse_json_object

    parsed = parse_json_object(text)
    usage = getattr(msg, "usage", None)
    in_t = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_t = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    return parsed, in_t, out_t

