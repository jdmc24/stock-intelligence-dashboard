from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import Any, AsyncIterator, Awaitable, Callable
from uuid import uuid4

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]

SSE_HEARTBEAT_SECONDS = 12.0


class AskEventEmitter:
    """Builds monotonic SSE event payloads for a single ask run."""

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or str(uuid4())
        self.seq = 0

    def next(self, event_type: str, **payload: Any) -> dict[str, Any]:
        self.seq += 1
        return {
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "type": event_type,
            **payload,
        }


def format_sse(event: dict[str, Any]) -> str:
    """One Server-Sent Events frame."""
    etype = event.get("type", "message")
    return f"event: {etype}\ndata: {json.dumps(event, default=str)}\n\n"


async def sse_stream(run: Callable[[AskEventEmitter, EventCallback], Awaitable[None]]) -> AsyncIterator[str]:
    """Run an ask pipeline and yield SSE frames."""
    emitter = AskEventEmitter()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    done = asyncio.Event()

    async def on_event(event: dict[str, Any]) -> None:
        await queue.put(format_sse(event))

    async def heartbeat() -> None:
        try:
            while not done.is_set():
                await asyncio.sleep(SSE_HEARTBEAT_SECONDS)
                if done.is_set():
                    break
                await queue.put(format_sse(emitter.next("ping")))
        except asyncio.CancelledError:
            return

    async def producer() -> None:
        try:
            await run(emitter, on_event)
        except Exception as e:
            err = emitter.next("error", code="INTERNAL", message=str(e), recoverable=False)
            await queue.put(format_sse(err))
            end = emitter.next("run_end", status="error")
            await queue.put(format_sse(end))
        finally:
            done.set()
            await queue.put(None)

    producer_task = asyncio.create_task(producer())
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk
    finally:
        done.set()
        heartbeat_task.cancel()
        with asyncio.suppress(asyncio.CancelledError):
            await heartbeat_task
        await producer_task
