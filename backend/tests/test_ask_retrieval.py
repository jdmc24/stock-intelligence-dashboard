from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import require_bearer_token
from app.db import get_session
from app.models import Base, Transcript
from app.routers.ask import router
from app.services.ask import orchestrator
from app.services import ticker_resolution, transcript_fetch_service
from app.services.sec_ticker_registry import SecCompanyEntry


REGISTRY = [
    SecCompanyEntry("SAY", "SARATOGA INVESTMENT CORP."),
    SecCompanyEntry("ESTC", "Elastic N.V."),
    SecCompanyEntry("ON", "ON SEMICONDUCTOR CORP."),
    SecCompanyEntry("RACE", "Ferrari N.V."),
    SecCompanyEntry("MSFT", "Microsoft Corporation"),
    SecCompanyEntry("BRK-B", "Berkshire Hathaway Inc."),
    SecCompanyEntry("GOOG", "Alphabet Inc."),
    SecCompanyEntry("GOOGL", "Alphabet Inc."),
]


class AskRetrievalTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(engine.dispose)
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async def session_override():
            async with self.sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[require_bearer_token] = lambda: None
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

        for target, name, replacement in (
            (ticker_resolution, "load_sec_registry", AsyncMock(return_value=REGISTRY)),
            (orchestrator, "session_context", self.sessions),
            (orchestrator.settings, "anthropic_api_key", None),
        ):
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def ask(self, question):
        response = await self.client.post("/api/ask/stream", json={"question": question})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "run_end")
        return events

    async def test_resolves_issuer_names_and_explicit_symbols_only(self):
        async with self.sessions() as session:
            for question, expected in (
                ("What did ferrari say on its last earnings call?", ["RACE"]),
                ("What did MSFT say on its last earnings call?", ["MSFT"]),
                ("Summarize high-severity banking regulations from the last 90 days.", []),
                ("What did $ON say on its last call?", ["ON"]),
                ("Compare earnings for BRK.B and $MSFT.", ["BRK-B", "MSFT"]),
                ("Compare Ferrari and Microsoft earnings.", ["RACE", "MSFT"]),
                ("What did Alphabet say on its last earnings call?", ["GOOGL"]),
            ):
                with self.subTest(question=question):
                    tickers, _ = await ticker_resolution.resolve_tickers_for_question(session, question)
                    self.assertEqual(tickers, expected)

    async def test_fetches_and_cites_a_transcript_before_answering(self):
        raw = "Operator: Welcome to the earnings call. CEO: Demand for electric vehicles increased. " * 6
        with patch.object(transcript_fetch_service, "earningscall_fetch_transcript", new_callable=AsyncMock) as provider:
            provider.return_value = raw, "Ferrari N.V.", None, None, "Q3-2025"
            events = await self.ask("What did ferrari say about electric vehicles on its last earnings call?")
            provider.assert_awaited_once()
            self.assertEqual(provider.call_args.kwargs["ticker"], "RACE")
            provider.reset_mock()
            cached = await self.ask("What did Ferrari say in its Q3 2025 earnings call?")
            provider.assert_not_awaited()

        for run in (events, cached):
            plan = next(event for event in run if event["type"] == "plan")
            self.assertEqual(plan["intent"]["tickers"], ["RACE"])
            retrieved = next(event for event in run if event["type"] == "tool_end"
                             and event["tool"] == "retrieve_earnings_transcripts")
            answer = next(event for event in run if event["type"] == "answer")
            self.assertLess(retrieved["seq"], answer["seq"])
            self.assertTrue(retrieved["output"]["found"])
            self.assertEqual(
                [citation["id"] for citation in answer["citations"] if citation["kind"] == "transcript"],
                retrieved["output"]["transcript_ids"],
            )
            self.assertIn("Demand for electric vehicles increased", answer["markdown"])
            self.assertFalse(any(event.get("agent") == "regulations" for event in run))

    async def test_explicit_quarter_does_not_reuse_another_call(self):
        async with self.sessions() as session:
            session.add(Transcript(ticker="MSFT", quarter="Q1-2025", source="upload",
                                   raw_text="CEO: Demand increased. " * 8, status="raw"))
            await session.commit()
        with patch.object(transcript_fetch_service, "earningscall_fetch_transcript", new_callable=AsyncMock) as provider:
            provider.side_effect = transcript_fetch_service.EarningsCallError("not available")
            events = await self.ask("What did MSFT say on its Q2 2025 earnings call?")
            self.assertEqual(provider.call_args.kwargs["quarter_label"], "Q2-2025")
        answer = next(event for event in events if event["type"] == "answer")
        self.assertIn("Q2-2025", answer["markdown"])
        self.assertEqual(answer["citations"], [])
        self.assertEqual(events[-1]["status"], "partial")

    async def test_timeout_reports_gap_without_synthesizing_earnings(self):
        async def slow_provider(*args, **kwargs):
            await asyncio.Event().wait()

        with patch.object(orchestrator, "_EARNINGS_RETRIEVAL_TIMEOUT", 0.02), \
             patch.object(orchestrator, "retrieve_ask_transcripts", side_effect=slow_provider), \
             patch.object(orchestrator, "_synthesize", new_callable=AsyncMock) as synthesize:
            events = await self.ask("What did MSFT say on its last earnings call?")
            synthesize.assert_not_awaited()

        answer = next(event for event in events if event["type"] == "answer")
        retrieval = next(event for event in events if event["type"] == "tool_end")
        self.assertTrue(retrieval["is_error"])
        self.assertIn("timed out", answer["markdown"])
        self.assertEqual(answer["citations"], [])
        self.assertEqual(events[-1]["status"], "partial")
