"""One-shot regulatory pipeline for cron/systemd. Usage: cd backend && python -m app.regulatory_pipeline"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


async def _main() -> None:
    from app.services.regulatory_scheduler import run_regulatory_pipeline_cli

    out = await run_regulatory_pipeline_cli()
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    asyncio.run(_main())
