from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from collections import Counter
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_research.prompts import (
    DAILY_BRIEF_SYSTEM,
    DAILY_BRIEF_USER,
    MARKET_RESEARCH_CLASSIFIER_SYSTEM,
    MARKET_RESEARCH_CLASSIFIER_USER,
)
from app.market_research.sources import SourceItem, fetch_hacker_news_items, fetch_rss_items
from app.models import DailyResearchBrief, MarketResearchInsight, MarketResearchItem
from app.services.llm.openai_client import complete_json_with_usage
from app.settings import settings

logger = logging.getLogger(__name__)


def _rss_urls() -> list[str]:
    return [url.strip() for url in settings.market_research_rss_urls.split(",") if url.strip()]


async def fetch_market_research_sources(*, lookback_hours: int, max_items: int) -> list[SourceItem]:
    timeout = httpx.Timeout(20.0, connect=8.0)
    headers = {"User-Agent": f"stock-intelligence.io market research crawler ({settings.sec_user_agent})"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        tasks = [fetch_hacker_news_items(client=client, lookback_hours=lookback_hours)]
        rss_urls = _rss_urls()
        if rss_urls:
            tasks.append(fetch_rss_items(client=client, urls=rss_urls, lookback_hours=lookback_hours))
        batches = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[SourceItem] = []
    for batch in batches:
        if isinstance(batch, Exception):
            logger.warning("market_research_source_fetch_failed error=%s", batch)
            continue
        items.extend(batch)

    seen: set[tuple[str, str]] = set()
    deduped: list[SourceItem] = []
    for item in items:
        key = (item.source, item.source_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    deduped.sort(key=lambda i: i.published_at or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True)
    return deduped[:max_items]


async def persist_source_items(session: AsyncSession, items: list[SourceItem]) -> list[MarketResearchItem]:
    persisted: list[MarketResearchItem] = []
    for item in items:
        existing = await session.scalar(
            select(MarketResearchItem).where(
                MarketResearchItem.source == item.source,
                MarketResearchItem.source_id == item.source_id,
            )
        )
        if existing is not None:
            persisted.append(existing)
            continue
        row = MarketResearchItem(
            source=item.source,
            source_id=item.source_id,
            url=item.url,
            title=item.title,
            text_excerpt=item.text[:4000],
            author_hash=item.author_hash,
            published_at=item.published_at,
            metadata_json=json.dumps(item.metadata, default=str),
        )
        session.add(row)
        persisted.append(row)
    await session.commit()
    return persisted


async def classify_item(session: AsyncSession, item: MarketResearchItem) -> MarketResearchInsight:
    existing = await session.scalar(select(MarketResearchInsight).where(MarketResearchInsight.item_id == item.id))
    if existing is not None:
        return existing

    if settings.openai_api_key:
        payload, input_tokens, output_tokens = await asyncio.to_thread(
            complete_json_with_usage,
            MARKET_RESEARCH_CLASSIFIER_SYSTEM,
            MARKET_RESEARCH_CLASSIFIER_USER.format(
                source=item.source,
                title=item.title,
                url=item.url,
                text=item.text_excerpt,
            ),
            2048,
        )
    else:
        payload = _heuristic_classification(item)
        input_tokens = 0
        output_tokens = 0

    insight = MarketResearchInsight(
        item_id=item.id,
        relevance=float(payload.get("relevance") or 0),
        persona=str(payload.get("persona") or "unknown")[:64],
        pain_point=str(payload.get("pain_point") or "")[:1000],
        current_workaround=str(payload.get("current_workaround") or "")[:1000],
        desired_feature=str(payload.get("desired_feature") or "")[:1000],
        urgency=str(payload.get("urgency") or "low")[:16],
        willingness_to_pay=str(payload.get("willingness_to_pay") or "low")[:16],
        feature_category=str(payload.get("feature_category") or "other")[:64],
        mentioned_tickers_json=json.dumps(payload.get("mentioned_tickers") or []),
        evidence_summary=str(payload.get("evidence_summary") or "")[:1000],
        model_used=settings.openai_model if settings.openai_api_key else "heuristic",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    session.add(insight)
    await session.commit()
    await session.refresh(insight)
    return insight


async def classify_items(session: AsyncSession, items: list[MarketResearchItem]) -> list[MarketResearchInsight]:
    insights: list[MarketResearchInsight] = []
    for item in items:
        try:
            insights.append(await classify_item(session, item))
        except Exception:
            logger.exception("market_research_classification_failed item_id=%s", item.id)
    return insights


async def generate_daily_brief(
    session: AsyncSession,
    *,
    brief_date: dt.date | None = None,
    lookback_hours: int | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    date = brief_date or dt.datetime.now(dt.UTC).date()
    lookback = lookback_hours or settings.market_research_lookback_hours
    limit = max_items or settings.market_research_max_items

    source_items = await fetch_market_research_sources(lookback_hours=lookback, max_items=limit)
    rows = await persist_source_items(session, source_items)
    insights = await classify_items(session, rows)
    relevant = [i for i in insights if i.relevance >= 0.4]
    brief_payload = await _build_brief_payload(date, relevant)

    existing = await session.scalar(select(DailyResearchBrief).where(DailyResearchBrief.brief_date == date))
    if existing is None:
        existing = DailyResearchBrief(brief_date=date)
        session.add(existing)

    existing.title = str(brief_payload.get("title") or f"Daily Customer Discovery Brief - {date.isoformat()}")
    existing.markdown = str(brief_payload.get("markdown") or _fallback_markdown(date, relevant))
    existing.executive_summary = str(brief_payload.get("executive_summary") or "")
    existing.top_pains_json = json.dumps(brief_payload.get("top_pains") or [])
    existing.suggested_experiments_json = json.dumps(brief_payload.get("suggested_experiments") or [])
    existing.source_item_count = len(rows)
    existing.insight_count = len(relevant)
    existing.updated_at = dt.datetime.now(dt.UTC)
    await session.commit()
    await session.refresh(existing)

    return {
        "ok": True,
        "brief_id": existing.id,
        "brief_date": existing.brief_date.isoformat(),
        "source_item_count": len(rows),
        "insight_count": len(relevant),
        "title": existing.title,
    }


async def latest_brief(session: AsyncSession) -> DailyResearchBrief | None:
    return await session.scalar(select(DailyResearchBrief).order_by(DailyResearchBrief.brief_date.desc()))


async def list_briefs(session: AsyncSession, *, limit: int = 20) -> list[DailyResearchBrief]:
    result = await session.execute(select(DailyResearchBrief).order_by(DailyResearchBrief.brief_date.desc()).limit(limit))
    return list(result.scalars().all())


async def market_research_status(session: AsyncSession) -> dict[str, Any]:
    item_count = await session.scalar(select(func.count()).select_from(MarketResearchItem))
    insight_count = await session.scalar(select(func.count()).select_from(MarketResearchInsight))
    brief_count = await session.scalar(select(func.count()).select_from(DailyResearchBrief))
    latest = await latest_brief(session)
    return {
        "items": item_count or 0,
        "insights": insight_count or 0,
        "briefs": brief_count or 0,
        "latest_brief_date": latest.brief_date.isoformat() if latest else None,
        "scheduler_enabled": settings.market_research_scheduler_enabled,
        "rss_feed_count": len(_rss_urls()),
    }


async def _build_brief_payload(date: dt.date, insights: list[MarketResearchInsight]) -> dict[str, Any]:
    insight_dicts = [_insight_dict(i) for i in insights[:40]]
    if settings.openai_api_key and insight_dicts:
        payload, _input_tokens, _output_tokens = await asyncio.to_thread(
            complete_json_with_usage,
            DAILY_BRIEF_SYSTEM,
            DAILY_BRIEF_USER.format(
                brief_date=date.isoformat(),
                insights_json=json.dumps(insight_dicts, default=str),
            ),
            4096,
        )
        return payload
    return _fallback_brief_payload(date, insights)


def _insight_dict(insight: MarketResearchInsight) -> dict[str, Any]:
    return {
        "persona": insight.persona,
        "pain_point": insight.pain_point,
        "desired_feature": insight.desired_feature,
        "urgency": insight.urgency,
        "willingness_to_pay": insight.willingness_to_pay,
        "feature_category": insight.feature_category,
        "evidence_summary": insight.evidence_summary,
        "relevance": insight.relevance,
    }


def _heuristic_classification(item: MarketResearchItem) -> dict[str, Any]:
    text = f"{item.title} {item.text_excerpt}".lower()
    relevant_terms = [
        "stock",
        "equity",
        "earnings",
        "10-k",
        "10-q",
        "sec filing",
        "financial analysis",
        "investing",
        "valuation",
        "transcript",
        "finfluencer",
        "stock tips",
        "social media investing",
        "chatgpt investing",
        "ai stock research",
        "etf",
        "investor relations",
        "shareholder",
    ]
    relevance = 0.75 if any(term in text for term in relevant_terms) else 0.2
    category = "research_workflow"
    if "earnings" in text or "transcript" in text:
        category = "earnings_call_analysis"
    elif "finfluencer" in text or "stock tips" in text or "claim" in text:
        category = "claim_checking"
    elif "social media" in text or "stocktwits" in text or "reddit" in text:
        category = "social_sentiment"
    elif "etf" in text or "thematic fund" in text:
        category = "etf_exposure"
    elif "investor relations" in text or "shareholder" in text:
        category = "retail_ir_monitoring"
    elif "10-k" in text or "10-q" in text or "sec" in text or "filing" in text:
        category = "filing_monitoring"
    elif "alert" in text or "notify" in text:
        category = "alerts"
    return {
        "relevance": relevance,
        "persona": "unknown",
        "pain_point": item.title if relevance >= 0.4 else "",
        "current_workaround": "",
        "desired_feature": item.title if relevance >= 0.4 else "",
        "urgency": "medium" if relevance >= 0.4 else "low",
        "willingness_to_pay": "low",
        "feature_category": category,
        "mentioned_tickers": [],
        "evidence_summary": item.text_excerpt[:240],
    }


def _fallback_brief_payload(date: dt.date, insights: list[MarketResearchInsight]) -> dict[str, Any]:
    categories = Counter(i.feature_category for i in insights)
    top = [
        {
            "pain": i.pain_point or i.evidence_summary,
            "who": i.persona,
            "why_it_matters": f"Maps to {i.feature_category.replace('_', ' ')}.",
            "evidence_count": categories[i.feature_category],
            "suggested_experiment": i.desired_feature or "Add a fake-door CTA and measure clicks.",
        }
        for i in insights[:5]
    ]
    return {
        "title": f"Daily Customer Discovery Brief - {date.isoformat()}",
        "executive_summary": f"Found {len(insights)} relevant market-research signals.",
        "top_pains": top,
        "suggested_experiments": [p["suggested_experiment"] for p in top],
        "interview_targets": sorted({i.persona for i in insights if i.persona != "unknown"})[:5],
        "markdown": _fallback_markdown(date, insights),
    }


def _fallback_markdown(date: dt.date, insights: list[MarketResearchInsight]) -> str:
    lines = [f"# Daily Customer Discovery Brief - {date.isoformat()}", ""]
    if not insights:
        lines.extend(["No strong customer-discovery signals found in today's crawl.", ""])
        return "\n".join(lines)
    for insight in insights[:10]:
        lines.extend(
            [
                f"## {insight.feature_category.replace('_', ' ').title()}",
                f"- Persona: {insight.persona}",
                f"- Pain: {insight.pain_point or insight.evidence_summary}",
                f"- Desired feature: {insight.desired_feature or 'Unknown'}",
                f"- Urgency: {insight.urgency}; willingness to pay: {insight.willingness_to_pay}",
                "",
            ]
        )
    return "\n".join(lines)
