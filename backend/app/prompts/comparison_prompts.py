from __future__ import annotations

import json

JSON_ONLY = "Respond with a single valid JSON object only. No markdown, no explanation."

COMPARISON_SYSTEM = f"""You compare earnings call analyses for the SAME company across quarters.
{JSON_ONLY}

Use the provided per-quarter analysis JSON (sentiment, hedging, guidance, topics). Infer quarter-over-quarter shifts.

Schema (fill arrays; use empty arrays if nothing notable):
{{
  "company": "string (ticker)",
  "company_name": "string or null",
  "quarters_compared": ["Q3-2025", "Q4-2025"],
  "key_shifts": [
    {{
      "topic": "string",
      "earlier_tone": "string (label for older quarter)",
      "later_tone": "string (label for newer quarter)",
      "evidence": "short quote or paraphrase citing both",
      "interpretation": "1-3 sentences for an investor"
    }}
  ],
  "new_topics": ["string"],
  "dropped_topics": ["string"],
  "guidance_changes": [
    {{
      "metric": "string",
      "earlier_guidance": "string or null",
      "later_guidance": "string or null",
      "change": "raised|lowered|maintained|withdrawn|unknown",
      "language_shift": "string or null"
    }}
  ],
  "hedging_shift": "string (brief summary of hedging language change, or empty)",
  "qa_highlights": ["string (optional: Q&A pressure or defensive moments if inferable)"],
  "executive_summary": "2-5 sentences on what changed that matters most"
}}"""


def analyses_block(
    ticker: str,
    company_name: str | None,
    quarters_payload: list[dict],
) -> str:
    meta = f"Ticker: {ticker}\n"
    if company_name:
        meta += f"Company: {company_name}\n"
    meta += "\n--- PER-QUARTER ANALYSIS JSON (oldest to newest) ---\n\n"

    for i, block in enumerate(quarters_payload):
        meta += f"### Quarter block {i + 1}\n"
        meta += json.dumps(block, ensure_ascii=False, indent=2)
        meta += "\n\n"
    return meta
