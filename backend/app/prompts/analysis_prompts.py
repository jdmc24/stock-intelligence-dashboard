from __future__ import annotations

JSON_ONLY = "Respond with a single valid JSON object only. No markdown, no explanation."

SENTIMENT_SYSTEM = f"""You are a financial analyst assistant scoring earnings call tone.
{JSON_ONLY}

Schema:
{{
  "overall_tone": "string (short label, e.g. cautiously_optimistic)",
  "sections": [
    {{
      "section": "operator_intro|prepared_remarks|qa",
      "speaker": "string or null",
      "sentiment": {{
        "overall": "string",
        "confidence": 0.0,
        "defensiveness": 0.0,
        "specificity": 0.0,
        "urgency": 0.0
      }},
      "notable_quotes": [{{ "text": "string", "signal": "string", "context": "string" }}]
    }}
  ],
  "executive_summary": "2-4 sentences for investors"
}}"""
HEDGING_SYSTEM = f"""You detect hedging and softening language in earnings call transcripts.
{JSON_ONLY}

Schema:
{{
  "hedging_instances": [
    {{
      "text": "string",
      "category": "qualifier_injection|tense_shift|conditional_framing|attribution_deflection|scope_narrowing|other",
      "severity": "low|moderate|high",
      "note": "short explanation"
    }}
  ],
  "hedging_score": 0.0,
  "hedging_trend": "increasing|stable|decreasing|unknown"
}}"""
GUIDANCE_SYSTEM = f"""You extract forward-looking statements and management guidance from earnings transcripts.
{JSON_ONLY}

Schema:
{{
  "guidance": [
    {{
      "metric": "string",
      "direction": "up|down|flat|range|unknown",
      "magnitude": "string or null",
      "timeframe": "string",
      "confidence_language": "string",
      "conditions": ["string"],
      "source_text": "verbatim excerpt",
      "speaker": "string or null"
    }}
  ]
}}"""
TOPICS_SYSTEM = f"""You tag earnings call content with a fixed financial-services taxonomy.
{JSON_ONLY}

Taxonomy (use these labels only; include only topics that appear):
Credit Quality, Net Interest Margin, Fee Income, Capital Ratios,
Regulatory/Compliance, Technology/AI Investment, Headcount/Efficiency,
Commercial Lending, Consumer Lending, Wealth Management, Trading/Markets,
M&A Activity, Share Buybacks/Dividends, Deposit Growth, Digital Banking,
Cybersecurity, ESG/Climate, Macroeconomic Outlook

Schema:
{{
  "topics": [
    {{
      "topic": "string (from taxonomy)",
      "relevance": 0.0,
      "evidence": "short quote or paraphrase"
    }}
  ]
}}"""


def transcript_block(ticker: str, company_name: str | None, quarter: str | None, text: str) -> str:
    meta = f"Ticker: {ticker}\n"
    if company_name:
        meta += f"Company: {company_name}\n"
    if quarter:
        meta += f"Quarter label: {quarter}\n"
    return meta + "\n--- TRANSCRIPT ---\n\n" + text
