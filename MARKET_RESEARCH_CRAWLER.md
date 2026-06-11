# Daily Market Research Crawler

This sandbox copy adds a bounded customer-discovery crawler for stock-intelligence.io.

## What It Does

- Fetches permitted public signals from Hacker News Algolia and optional RSS feeds.
- Normalizes source items into SQLite.
- Classifies each item as customer-discovery signal for an AI equity research product.
- Uses OpenAI when `OPENAI_API_KEY` is configured; otherwise falls back to a simple heuristic classifier.
- Generates and stores a daily Markdown brief.

## Environment

Add these to `backend/.env` when you want the in-process daily scheduler:

```env
MARKET_RESEARCH_SCHEDULER_ENABLED=true
MARKET_RESEARCH_SCHEDULER_RUN_ON_STARTUP=false
MARKET_RESEARCH_SCHEDULER_HOUR=7
MARKET_RESEARCH_SCHEDULER_MINUTE=30
MARKET_RESEARCH_LOOKBACK_HOURS=24
MARKET_RESEARCH_MAX_ITEMS=40
MARKET_RESEARCH_RSS_URLS=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.4-mini
```

`MARKET_RESEARCH_RSS_URLS` is a comma-separated list. Leave it blank to use only Hacker News.

## API

All endpoints use the existing bearer-token dependency:

- `GET /api/market-research/status`
- `POST /api/market-research/briefs/trigger?lookback_hours=24&max_items=40`
- `GET /api/market-research/briefs/latest`
- `GET /api/market-research/briefs?limit=20`

## Local Manual Run

From `backend/`:

```bash
python -c '
import asyncio
from app.platform_init import init_platform_schema
from app.db import session_context
from app.market_research.service import generate_daily_brief

async def main():
    await init_platform_schema()
    async with session_context() as session:
        print(await generate_daily_brief(session, lookback_hours=24, max_items=40))

asyncio.run(main())
'
```

## Reddit

Reddit is intentionally not included as an HTML scraper. Add it only through approved/official API or licensed access.
