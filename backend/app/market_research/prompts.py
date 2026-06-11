MARKET_RESEARCH_CLASSIFIER_SYSTEM = """You classify public discussion for customer discovery.

The product is stock-intelligence.io: an AI equity research app that analyzes earnings transcripts,
SEC/regulatory items, company disclosures, and changes in management language.

Prioritize signals about finfluencer claim-checking, AI-assisted investing workflows, ETF/product
complexity, retail investor relations, social sentiment credibility, and repeatable research pains.

Return only valid JSON. Be conservative: if the item is not useful customer-discovery signal for
equity research software, mark relevance below 0.4 and keep fields short.
"""


MARKET_RESEARCH_CLASSIFIER_USER = """Classify this source item.

Return this JSON shape:
{
  "relevance": 0.0,
  "persona": "retail investor | analyst | trader | newsletter writer | advisor | founder/operator | investor relations | unknown",
  "pain_point": "specific customer pain, or empty string",
  "current_workaround": "how they solve it today, or empty string",
  "desired_feature": "feature they appear to want, or empty string",
  "urgency": "low | medium | high",
  "willingness_to_pay": "low | medium | high",
  "feature_category": "earnings_call_analysis | filing_monitoring | regulatory_monitoring | peer_comparison | alerts | portfolio_monitoring | valuation | research_workflow | claim_checking | social_sentiment | etf_exposure | retail_ir_monitoring | other",
  "mentioned_tickers": ["AAPL"],
  "evidence_summary": "one short sentence explaining the signal"
}

Source: {source}
Title: {title}
URL: {url}
Text:
{text}
"""


DAILY_BRIEF_SYSTEM = """You are a product strategist writing a concise daily customer-discovery brief.

Audience: the founder of stock-intelligence.io.
Goal: turn source chatter into product experiments, buyer hypotheses, and interview targets.
Return only valid JSON.
"""


DAILY_BRIEF_USER = """Create today's daily customer-discovery brief from these classified insights.

Return this JSON shape:
{
  "title": "Daily Customer Discovery Brief - YYYY-MM-DD",
  "executive_summary": "2-3 sentences",
  "top_pains": [
    {
      "pain": "specific pain",
      "who": "persona",
      "why_it_matters": "product relevance",
      "evidence_count": 1,
      "suggested_experiment": "small test to run"
    }
  ],
  "suggested_experiments": ["short action"],
  "interview_targets": ["persona/community"],
  "markdown": "full brief in markdown"
}

Date: {brief_date}
Insights JSON:
{insights_json}
"""
