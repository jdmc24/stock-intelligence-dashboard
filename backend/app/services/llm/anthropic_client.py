from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from anthropic import Anthropic

from app.settings import settings

_JSON_RETRY_USER = (
    "Your previous reply was not valid JSON. Respond with ONLY one JSON object matching the "
    "requested schema. No markdown fences, no commentary, no text before or after the object."
)


def get_client() -> Anthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return Anthropic(api_key=settings.anthropic_api_key)


def complete_json(system: str, user: str, max_tokens: int = 8192) -> dict:
    data, _in_t, _out_t = complete_json_with_usage(system, user, max_tokens=max_tokens)
    return data


def _parse_model_json(text: str) -> dict:
    from app.services.json_extract import parse_json_object

    return parse_json_object(text)


def complete_json_with_usage(system: str, user: str, max_tokens: int = 8192) -> tuple[dict, int, int]:
    """Returns (parsed_json, input_tokens, output_tokens)."""
    client = get_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    in_total = 0
    out_total = 0
    last_text = ""

    for attempt in range(2):
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        usage = getattr(msg, "usage", None)
        if usage:
            in_total += int(getattr(usage, "input_tokens", 0) or 0)
            out_total += int(getattr(usage, "output_tokens", 0) or 0)

        last_text = "".join(block.text for block in msg.content if block.type == "text")
        try:
            return _parse_model_json(last_text), in_total, out_total
        except ValueError:
            if attempt == 0:
                messages.append({"role": "assistant", "content": last_text or "(empty)"})
                messages.append({"role": "user", "content": _JSON_RETRY_USER})
                continue
            raise

    raise ValueError("No JSON object found in model output")


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _assistant_content_to_payload(content: list[Any]) -> list[dict[str, Any]]:
    """Convert SDK content blocks to plain dicts so we can replay them as
    the assistant turn in the next request."""
    out: list[dict[str, Any]] = []
    for b in content:
        btype = getattr(b, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": getattr(b, "text", "")})
        elif btype == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "id": getattr(b, "id", ""),
                    "name": getattr(b, "name", ""),
                    "input": getattr(b, "input", {}) or {},
                }
            )
    return out


def _extract_text(content: list[Any]) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")


async def complete_json_with_tools_and_usage(
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    execute_tool_async: ToolExecutor,
    max_iters: int = 4,
    max_tokens: int = 8192,
) -> tuple[dict, list[dict[str, Any]], int, int]:
    """Run a tool-using exchange with Claude.

    The model may call any of `tools` zero or more times (bounded by
    `max_iters`). Each tool call is dispatched via `execute_tool_async`, and
    the result is sent back to the model as a `tool_result` block. When the
    model finally returns text-only, the text is parsed as JSON.

    Returns:
        parsed_final_json: the dict parsed from the model's final text reply
        tool_calls_log: list of {"name", "input", "output", "is_error"} entries
                        suitable for persisting as a reasoning trace
        input_tokens_total, output_tokens_total: summed across all rounds
    """
    client = get_client()
    model = settings.anthropic_model
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    tool_calls_log: list[dict[str, Any]] = []
    in_total = 0
    out_total = 0

    for _round in range(max_iters):
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
            )
        )
        usage = getattr(msg, "usage", None)
        if usage is not None:
            in_total += int(getattr(usage, "input_tokens", 0) or 0)
            out_total += int(getattr(usage, "output_tokens", 0) or 0)

        tool_uses = [b for b in msg.content if getattr(b, "type", None) == "tool_use"]

        if not tool_uses:
            text = _extract_text(msg.content)
            try:
                return _parse_model_json(text), tool_calls_log, in_total, out_total
            except ValueError:
                messages.append({"role": "assistant", "content": _assistant_content_to_payload(msg.content)})
                messages.append({"role": "user", "content": _JSON_RETRY_USER})
                continue

        messages.append({"role": "assistant", "content": _assistant_content_to_payload(msg.content)})

        tool_results_content: list[dict[str, Any]] = []
        for tu in tool_uses:
            name = getattr(tu, "name", "")
            args = getattr(tu, "input", {}) or {}
            tu_id = getattr(tu, "id", "")
            try:
                result = await execute_tool_async(name, args)
                result_text = json.dumps(result, default=str)
                is_error = False
            except Exception as e:
                result = {"error": str(e)}
                result_text = json.dumps(result)
                is_error = True
            tool_calls_log.append(
                {"name": name, "input": args, "output": result, "is_error": is_error}
            )
            tool_results_content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": result_text,
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": tool_results_content})

    messages.append(
        {
            "role": "user",
            "content": "Return the final JSON object only now. Do not call any more tools.",
        }
    )
    for attempt in range(2):
        final = await asyncio.to_thread(
            lambda: client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
        )
        fusage = getattr(final, "usage", None)
        if fusage is not None:
            in_total += int(getattr(fusage, "input_tokens", 0) or 0)
            out_total += int(getattr(fusage, "output_tokens", 0) or 0)
        text = _extract_text(final.content)
        try:
            return _parse_model_json(text), tool_calls_log, in_total, out_total
        except ValueError:
            if attempt == 0:
                messages.append({"role": "assistant", "content": _assistant_content_to_payload(final.content)})
                messages.append({"role": "user", "content": _JSON_RETRY_USER})
                continue
            raise

    raise ValueError("No JSON object found in model output")
