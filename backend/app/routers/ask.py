from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_bearer_token
from app.db import get_session
from app.schemas import AskStreamIn
from app.services.ask.events import sse_stream
from app.services.ask.orchestrator import run_ask
from app.settings import settings

router = APIRouter(prefix="/api/ask", tags=["ask"])


@router.post("/stream", dependencies=[Depends(require_bearer_token)])
async def ask_stream(body: AskStreamIn, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    """Stream cross-domain Q&A as Server-Sent Events (SSE).

    Phase 1: orchestrator + regulations specialist. Earnings specialist hooks in later
    using the same event schema and /ask UI.
    """
    ctx = body.context.model_dump() if body.context else {}
    lookback = body.context.lookback_days if body.context else 90

    async def pipeline(emitter, on_event):
        await run_ask(
            session,
            question=body.question,
            context=ctx,
            lookback_days=lookback,
            emitter=emitter,
            emit=on_event,
        )

    if not settings.anthropic_api_key:
        # Still runs deterministic tool path + markdown fallback.

        async def pipeline_with_notice(emitter, on_event):
            await on_event(
                emitter.next(
                    "message",
                    level="info",
                    text="ANTHROPIC_API_KEY is not set — using database tools and a basic answer template.",
                )
            )
            await run_ask(
                session,
                question=body.question,
                context=ctx,
                lookback_days=lookback,
                emitter=emitter,
                emit=on_event,
            )

        gen = sse_stream(pipeline_with_notice)
    else:
        gen = sse_stream(pipeline)

    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
