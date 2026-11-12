from __future__ import annotations

import asyncio
import datetime as dt
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
from app.services.ask import earnings_filings, orchestrator
from app.services.ask.earnings_filings import EarningsFiling
from app.services import earningscall_client, ticker_resolution, transcript_fetch_service
from app.services.sec_ticker_registry import SecCompanyEntry


REGISTRY = [
    SecCompanyEntry("SAY", "SARATOGA INVESTMENT CORP."),
    SecCompanyEntry("ESTC", "Elastic N.V."),
    SecCompanyEntry("ON", "ON SEMICONDUCTOR CORP."),
    SecCompanyEntry("RACE", "Ferrari N.V."),
    SecCompanyEntry("LLY", "ELI LILLY & CO"),
    SecCompanyEntry("MSFT", "Microsoft Corporation"),
    SecCompanyEntry("NVDA", "NVIDIA Corporation"),
    SecCompanyEntry("UBER", "Uber Technologies, Inc."),
    SecCompanyEntry("BRK-B", "Berkshire Hathaway Inc.", "1067983"),
    SecCompanyEntry("BRK-A", "Berkshire Hathaway Inc.", "1067983"),
    SecCompanyEntry("CMG", "CHIPOTLE MEXICAN GRILL INC"),
    SecCompanyEntry("CRWD", "CrowdStrike Holdings, Inc."),
    SecCompanyEntry("DASH", "DoorDash, Inc."),
    SecCompanyEntry("NFLX", "NETFLIX INC"),
    SecCompanyEntry("PLTR", "Palantir Technologies Inc."),
    SecCompanyEntry("TGT", "TARGET CORP"),
    SecCompanyEntry("TH", "Target Hospitality Corp."),
    SecCompanyEntry("AMD", "ADVANCED MICRO DEVICES INC"),
    SecCompanyEntry("FYBR", "Frontier Communications Parent, Inc."),
    SecCompanyEntry("ULCC", "Frontier Group Holdings, Inc."),
    SecCompanyEntry("BAC", "BANK OF AMERICA CORP /DE/", "70858"),
    SecCompanyEntry("BAC-PB", "BANK OF AMERICA CORP /DE/", "70858"),
    SecCompanyEntry("CMCSA", "COMCAST CORP", "1166691"),
    SecCompanyEntry("CCZ", "COMCAST CORP", "1166691"),
    SecCompanyEntry("F", "FORD MOTOR CO", "37996"),
    SecCompanyEntry("F-PD", "FORD MOTOR CO", "37996"),
    SecCompanyEntry("GS", "GOLDMAN SACHS GROUP INC", "886982"),
    SecCompanyEntry("GS-PA", "GOLDMAN SACHS GROUP INC", "886982"),
    SecCompanyEntry("AAAU", "Goldman Sachs Physical Gold ETF", "1708646"),
    SecCompanyEntry("GSBD", "Goldman Sachs BDC, Inc.", "1572694"),
    SecCompanyEntry("DIS", "Walt Disney Co"),
    SecCompanyEntry("BKNG", "Booking Holdings Inc."),
    SecCompanyEntry("PEP", "PEPSICO INC"),
    SecCompanyEntry("LOW", "LOWES COMPANIES INC"),
    SecCompanyEntry("MCD", "MCDONALDS CORP"),
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

        self.calendar = AsyncMock(side_effect=lambda ticker, **_: {
            "UBER": (("Q3-2026", dt.datetime(2026, 11, 1, tzinfo=dt.UTC)),),
            "RACE": (("Q3-2025", dt.datetime(2025, 11, 1, tzinfo=dt.UTC)),),
            "LLY": (("Q3-2026", dt.datetime(2026, 11, 1, tzinfo=dt.UTC)),),
            "NVDA": (("Q3-2027", dt.datetime(2099, 11, 17, tzinfo=dt.UTC)), ("Q2-2027", dt.datetime(2026, 8, 26, tzinfo=dt.UTC)), ("Q3-2026", dt.datetime(2025, 11, 19, tzinfo=dt.UTC))),
        }.get(ticker, ()))
        self.filing_fallback = AsyncMock(return_value=None)
        for target, name, replacement in (
            (orchestrator, "fetch_earnings_filing", self.filing_fallback),
            (transcript_fetch_service, "earnings_call_calendar", self.calendar),
            (ticker_resolution, "load_sec_registry", AsyncMock(return_value=REGISTRY)),
            (orchestrator, "session_context", self.sessions),
            (orchestrator.settings, "anthropic_api_key", None),
        ):
            patcher = patch.object(target, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def ask(self, question, context=None):
        response = await self.client.post("/api/ask/stream", json={"question": question, "context": context})
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
                ("what did palantir say on its latest earnings call?", ["PLTR"]),
                ("summarize crowdstrike’s latest earnings call", ["CRWD"]),
                ("compare chipotle and doordash earnings", ["CMG", "DASH"]),
                ("tell me about the latest call for netflix", ["NFLX"]),
                ("what did amd report on its latest earnings call?", ["AMD"]),
                ("what did target report on its earnings call?", ["TGT"]),
                ("what did uber say about target margins on its last earnings call?", ["UBER"]),
                ("what did management say on its last earnings call?", []),
                ("What did ferrari say on its last earnings call?", ["RACE"]),
                ("what did bank of america say on its latest earnings call?", ["BAC"]),
                ("what did comcast say on its latest earnings call?", ["CMCSA"]),
                ("what did ford say on its latest earnings call?", ["F"]),
                ("what did berkshire hathaway say on its latest earnings call?", ["BRK-B"]),
                ("what did goldman sachs say on its latest earnings call?", ["GS"]),
                ("what did disney say on its latest earnings call?", ["DIS"]),
                ("what did booking.com say on its latest earnings call?", ["BKNG"]),
                ("what did pepsi say on its latest earnings call?", ["PEP"]),
                ("what did lowe’s say on its latest earnings call?", ["LOW"]),
                ("what did mcdonald’s say on its latest earnings call?", ["MCD"]),
                ("What did Alphabet say on its last earnings call?", ["GOOGL"]),
            ):
                with self.subTest(question=question):
                    tickers, _ = await ticker_resolution.resolve_tickers_for_question(session, question)
                    self.assertEqual(tickers, expected)

    async def test_ambiguous_common_name_asks_for_clarification(self):
        events = await self.ask(
            "what did frontier say on its latest earnings call?",
            {"follow_up_tickers": ["UBER"], "follow_up_earnings": True},
        )
        answer = next(event for event in events if event["type"] == "answer")
        self.assertIn("Which company did you mean", answer["markdown"])
        self.assertIn("FYBR", answer["markdown"])
        self.assertIn("ULCC", answer["markdown"])
        self.assertFalse(any(event["type"] == "tool_start" for event in events))
        choice = next(q for q in answer["follow_up_questions"] if "(ticker ULCC)" in q)
        async with self.sessions() as session:
            tickers, notes = await ticker_resolution.resolve_tickers_for_question(session, choice)
        self.assertEqual(tickers, ["ULCC"])
        self.assertEqual(notes, [])

    async def test_fetches_and_cites_a_transcript_before_answering(self):
        raw = "Operator: Welcome to the earnings call. CEO: Demand for electric vehicles increased. " * 6
        with patch.object(transcript_fetch_service, "earningscall_fetch_transcript", new_callable=AsyncMock) as provider:
            provider.return_value = raw, "Ferrari N.V.", None, None, "Q3-2025"
            events = await self.ask("What did ferrari say about electric vehicles on its last earnings call?")
            provider.assert_awaited_once()
            self.filing_fallback.assert_not_awaited()
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

    async def test_uber_by_name_retrieves_and_cites_earnings(self):
        with patch.object(transcript_fetch_service, "earningscall_fetch_transcript", new_callable=AsyncMock) as provider:
            provider.return_value = (
                "CEO: Mobility demand grew across several regions. " * 8, "Uber", None, None, "Q3-2026"
            )
            events = await self.ask("what did uber say on its latest earnings call?")
            self.assertEqual(provider.call_args.kwargs["ticker"], "UBER")
        plan = next(event for event in events if event["type"] == "plan")
        answer = next(event for event in events if event["type"] == "answer")
        self.assertEqual(plan["intent"]["tickers"], ["UBER"])
        self.assertIn("Mobility demand grew", answer["markdown"])
        self.assertTrue(any(c["kind"] == "transcript" for c in answer["citations"]))

    async def test_call_overview_reads_management_remarks(self):
        raw = (
            "Operator: Welcome to the earnings conference call. Later we will hold a question and answer session. "
            "I will now turn the call over to management. Please go ahead. "
            "CEO: We expanded manufacturing capacity and advanced our pipeline. "
            + "CFO: Revenue increased and we raised full-year guidance. " * 400
        )
        async with self.sessions() as session:
            session.add(Transcript(ticker="LLY", quarter="Q3-2026", source="earningscall",
                                   raw_text=raw, status="raw"))
            await session.commit()
        events = await self.ask(
            "tell me about the latest earnings call for eli lilly. what did the c-suite talk about?"
        )
        read = next(event for event in events if event.get("tool") == "read_earnings_transcripts"
                    and event["type"] == "tool_end")
        self.assertEqual(read["input"]["topic"], "")
        self.assertGreater(read["output"]["count"], 1)
        answer = next(event for event in events if event["type"] == "answer")
        self.assertIn("We expanded manufacturing capacity", answer["markdown"])
        self.assertIn("we raised full-year guidance", answer["markdown"])
        self.assertNotIn("I will now turn the call over", answer["markdown"])
        self.assertEqual(events[-1]["status"], "ok")

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

    async def test_refresh_and_free_form_follow_up_use_fiscal_periods(self):
        async with self.sessions() as session:
            session.add(Transcript(ticker="NVDA", quarter="Q4-2026", source="earningscall",
                                   raw_text="CEO: Previous call remarks. " * 8, status="raw"))
            await session.commit()
        with patch.object(transcript_fetch_service, "earningscall_fetch_transcript", new_callable=AsyncMock) as provider:
            provider.side_effect = lambda **kw: (
                "CEO: Data center demand increased. " * 8, "NVIDIA", None, None, kw["quarter_label"]
            )
            initial = await self.ask("Summarize NVIDIA's latest earnings call")
            answer = next(event for event in initial if event["type"] == "answer")
            self.assertEqual(answer["earnings_quarter"], "Q2-2027")
            context = {"follow_up_tickers": ["NVDA"], "follow_up_earnings": True,
                       "follow_up_quarter": answer["earnings_quarter"], "previous_question": "Summarize NVIDIA's latest earnings call"}
            await self.ask("What about data center demand?", context)
            spelled = await self.ask("What about the second quarter?", context)
            self.assertEqual(next(event for event in spelled if event["type"] == "answer")["earnings_quarter"], "Q2-2027")
            follow_up = await self.ask("Are you sure that's the most recent earnings transcript? How about Q3?", context)
            answer = next(event for event in follow_up if event["type"] == "answer")
            self.assertIn("Q3-2027 is scheduled", answer["markdown"])
            self.assertEqual(answer["citations"], [])
            self.assertEqual([call.kwargs["quarter_label"] for call in provider.await_args_list], ["Q2-2027"])
            self.calendar.assert_awaited_with("NVDA", force=True)

    async def test_unavailable_latest_is_labeled_as_cached(self):
        async with self.sessions() as session:
            session.add(Transcript(ticker="NVDA", quarter="Q4-2026", source="earningscall",
                                   raw_text="CEO: Previous call remarks. " * 8, status="raw"))
            await session.commit()
        with patch.object(transcript_fetch_service, "earningscall_fetch_transcript", new_callable=AsyncMock) as provider:
            provider.side_effect = transcript_fetch_service.EarningsCallError("not available")
            events = await self.ask("What did NVDA say on its latest call?")
        answer = next(event for event in events if event["type"] == "answer")
        self.assertEqual(answer["earnings_quarter"], "Q4-2026")
        self.assertTrue(any("Q2-2027" in limit and "on file" in limit for limit in answer["limitations"]))
        self.assertEqual(events[-1]["status"], "partial")

    async def test_provider_rate_limit_keeps_cached_evidence(self):
        async with self.sessions() as session:
            session.add(Transcript(ticker="NVDA", quarter="Q2-2027", source="earningscall",
                                   raw_text="CEO: Prior call remarks. " * 8, status="raw"))
            await session.commit()
        self.calendar.side_effect = earningscall_client.EarningsCallBusy("Rate-limited")
        events = await self.ask("What did NVIDIA say on its latest earnings call?")
        answer = next(event for event in events if event["type"] == "answer")
        self.assertEqual(answer["earnings_quarter"], "Q2-2027")
        self.assertTrue(any("rate-limited" in item and "on file" in item for item in answer["limitations"]))

    async def test_provider_honors_retry_after_without_sending_another_request(self):
        hits = []

        def handle(request):
            hits.append(request.url.path)
            return httpx.Response(429, headers={"Retry-After": "10"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="https://test") as client:
            with patch.object(earningscall_client, "_retry_after", 0):
                for _ in range(2):
                    with self.assertRaises(earningscall_client.EarningsCallBusy):
                        await earningscall_client._provider_get(client, "/events")
        self.assertEqual(hits, ["/events"])

    async def test_missing_transcript_uses_and_cites_filing(self):
        self.filing_fallback.return_value = EarningsFiling(
            ticker="BRK-B", quarter="Q3-2026", kind="sec_filing", label="Form 10-Q",
            url="https://www.sec.gov/Archives/edgar/data/1067983/000119312526452412/brka-20260930.htm",
            accession="0001193125-26-452412", period_end=dt.date(2026, 9, 30),
            text="Net income for the quarter: 22,112,000,000 USD.",
        )
        with patch.object(orchestrator, "retrieve_ask_transcripts", AsyncMock(return_value=([], None))):
            events = await self.ask("What did Berkshire Hathaway say on its latest earnings call?")
        answer = next(event for event in events if event["type"] == "answer")
        self.assertIn("no call transcript was available", answer["markdown"])
        self.assertIn("22,112,000,000 USD", answer["markdown"])
        self.assertEqual(answer["earnings_quarter"], "Q3-2026")
        self.assertEqual(answer["citations"], [{
            "kind": "sec_filing", "id": "0001193125-26-452412", "label": "BRK-B Q3-2026 Form 10-Q",
            "href": self.filing_fallback.return_value.url,
        }])
        self.assertTrue(any(e.get("tool") == "retrieve_earnings_filings" and e.get("output", {}).get("found")
                            for e in events))

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


class EarningsFilingsTest(unittest.IsolatedAsyncioTestCase):
    async def test_release_preferred_then_matching_10q(self):
        accession = "0001193125-26-452412"
        submissions = {"fiscalYearEnd": "1231", "filings": {"recent": {
            "form": ["8-K", "10-Q"],
            "accessionNumber": ["0001193125-26-452530", accession],
            "primaryDocument": ["cover.htm", "report.htm"],
            "reportDate": ["2026-11-07", "2026-09-30"],
            "filingDate": ["2026-11-09", "2026-11-09"],
            "items": ["2.02,9.01", ""],
        }}}
        facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
            {"accn": accession, "start": "2026-01-01", "end": "2026-09-30", "val": 57, "fp": "Q3", "fy": 2026},
            {"accn": accession, "start": "2026-07-01", "end": "2026-09-30", "val": 22, "fp": "Q3", "fy": 2026},
            {"accn": "0001193125-25-123456", "start": "2026-07-01", "end": "2026-09-30", "val": 99},
        ]}}}}}
        release_available = True

        def handle(request):
            path = request.url.path
            if path.startswith("/submissions/"):
                return httpx.Response(200, json=submissions)
            if path.startswith("/api/xbrl/companyfacts/"):
                return httpx.Response(200, json=facts)
            if not release_available:
                return httpx.Response(403)
            if path.endswith("/cover.htm"):
                return httpx.Response(200, text=(
                    'Quarter ended September 30, 2026. <a href="https://example.com/exhibit.htm">Exhibit 99.1</a>'
                    '<a href="release.htm">Exhibit 99.1</a>'
                ))
            if path.endswith("/release.htm"):
                return httpx.Response(200, text="<p>Net income grew in the third quarter.</p>" * 20)
            return httpx.Response(404)

        create_client = httpx.AsyncClient
        with patch.object(earnings_filings, "load_sec_registry", AsyncMock(return_value=REGISTRY)), \
             patch.object(earnings_filings.httpx, "AsyncClient",
                          side_effect=lambda **kwargs: create_client(transport=httpx.MockTransport(handle), **kwargs)):
            release = await earnings_filings.fetch_earnings_filing("BRK-B", "Q3-2026")
            self.assertEqual(release.kind, "earnings_release")
            self.assertTrue(release.url.endswith("/release.htm"))
            release_available = False
            filing = await earnings_filings.fetch_earnings_filing("BRK-B", "Q3-2026")
            self.assertEqual(filing.kind, "sec_filing")
            self.assertIn("2026-07-01 through 2026-09-30): 22 USD", filing.text)
            self.assertIsNone(await earnings_filings.fetch_earnings_filing("BRK-B", "Q4-2026"))


    async def test_uses_reported_fiscal_year_for_noncalendar_issuer(self):
        accession = "0000028917-26-000027"
        submissions = {"fiscalYearEnd": "0130", "filings": {"recent": {
            "form": ["10-Q"], "accessionNumber": [accession],
            "primaryDocument": ["dds-20260801x10q.htm"], "reportDate": ["2026-08-01"],
            "filingDate": ["2026-08-28"], "items": [""],
        }}}
        facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
            {"accn": accession, "start": "2026-05-03", "end": "2026-08-01",
             "val": 97700000, "fp": "Q2", "fy": 2026},
        ]}}}}}

        def handle(request):
            path = request.url.path
            if path.startswith("/submissions/"):
                return httpx.Response(200, json=submissions)
            if path.startswith("/api/xbrl/companyfacts/"):
                return httpx.Response(200, json=facts)
            return httpx.Response(404)

        create_client = httpx.AsyncClient
        registry = [SecCompanyEntry("DDS", "Dillard’s, Inc.", "28917")]
        with patch.object(earnings_filings, "load_sec_registry", AsyncMock(return_value=registry)), \
             patch.object(earnings_filings.httpx, "AsyncClient",
                          side_effect=lambda **kwargs: create_client(transport=httpx.MockTransport(handle), **kwargs)):
            filing = await earnings_filings.fetch_earnings_filing("DDS", "Q2-2026")
            self.assertEqual(filing.quarter, "Q2-2026")
            self.assertEqual(filing.accession, accession)
            self.assertIn("97,700,000 USD", filing.text)
            self.assertIsNone(await earnings_filings.fetch_earnings_filing("DDS", "Q2-2027"))
