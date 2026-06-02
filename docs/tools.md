# Tools catalog

This project uses **LLM tool calling** in two places: the **Ask orchestrator** (cross-domain Q&A) and the **regulations enrichment pipeline** (tagging ingested Federal Register documents). Earnings analysis uses direct LLM prompts, not a tool loop.

Tool definitions live in code; this document is the reference for what exists and when each tool runs.

---

## Ask — Regulations specialist

**Agent:** `regulations` · **Module:** `backend/app/services/ask/regulations_tools.py`  
**Prompt:** `backend/app/prompts/ask_prompts.py` → `REGULATIONS_AGENT_SYSTEM`

| Tool | Purpose | Key inputs | Notes |
|------|---------|------------|-------|
| **`lookup_company_ticker`** | **Resolve company name → ticker(s)** | `company_name`, `limit` | **Shared.** SEC registry + app DB names |
| `lookup_company_profile` | Load ticker regulatory profile (products, functions, institution types) | `ticker` | Shared with enrichment tools |
| `search_related_regulations` | Keyword search on title/abstract of prior FR docs | `query`, `limit` | Shared with enrichment tools |
| **`search_regulations`** | **Filtered search over ingested + enriched FR docs** | `search`, `severity_min`, `lookback_days`, `institution_type`, `agency`, `limit` | **New.** Use for “high-severity banking rules in 90 days” |
| `impact_by_ticker` | Enriched docs in lookback window that overlap a company profile | `ticker`, `lookback_days` | Tag overlap, not general sector search |
| `list_regulations` | Simple keyword search (title/abstract/body) | `search`, `limit` | No severity/date filters |
| `get_regulation` | Load one document by internal uuid | `document_id` | Used when user opens Ask from a regulation page |

### `search_regulations` filters

| Parameter | Values | Behavior |
|-----------|--------|----------|
| `severity_min` | `low` · `medium` · `high` · `critical` | Includes that level and above (e.g. `high` → high + critical) |
| `lookback_days` | 1–365 (default 90) | `publication_date >= today - N days` |
| `institution_type` | `commercial_bank`, `credit_union`, `mortgage_servicer`, `broker_dealer`, `fintech`, `insurance`, `other` | Matches enriched `institution_types` JSON |
| `agency` | free text | Substring match on document `agencies` JSON (e.g. `OCC`, `FDIC`, `CFPB`) |
| `search` | optional keyword | Title, abstract, or search_text |

Requires **enriched** documents for severity and institution filters. Empty results include a `note` about ingest/enrich pipeline status.

**Implementation:** `backend/app/services/regulations_service.py` → `search_regulations()`

---

## Ask — Earnings specialist

**Agent:** `earnings` · **Module:** `backend/app/services/ask/earnings_tools.py`  
**Prompt:** `backend/app/prompts/ask_prompts.py` → `EARNINGS_AGENT_SYSTEM`

| Tool | Purpose | Key inputs | Notes |
|------|---------|------------|-------|
| **`lookup_company_ticker`** | **Resolve company name → ticker(s)** | `company_name`, `limit` | **Shared with regulations agent.** SEC registry + app DB |
| `list_transcripts_for_ticker` | List stored earnings calls for a ticker | `ticker`, `limit` | Read-only |
| `get_transcript_analysis` | Load AI analysis (summary, sentiment, topics, guidance) | `transcript_id` | Does not start new analysis jobs |
| `search_transcript_quotes` | Find speaker sections containing a phrase | `query`, `company` | Best for “how they talked about AI” |
| `search_transcripts` | Full-text keyword search in transcript bodies | `company`, `q` / `topic`, `limit` | Returns snippets |
| `company_earnings_timeline` | Per-quarter tone, hedging, topics for analyzed calls | `ticker` | Needs analyzed transcripts |

**Auto-fetch (orchestrator, not an LLM tool):** Before the earnings agent runs, `ensure_transcripts_for_ticker()` tries **EarningsCall** when `EARNINGSCALL_API_KEY` is set, then falls back to **SEC EDGAR** (latest earnings transcript from recent 8-K exhibits). The system aims to store **up to 32 recent quarters (~8 years)** per ticker; each Ask run fetches at most **12 new quarters** incrementally so responses stay fast. “Latest call” questions prefetch at least 2 quarters when available; trend/compare questions target the full 32-quarter goal.

| Tool | Reads DB | Writes / fetches |
|------|----------|------------------|
| All earnings tools below | Yes | No |
| Orchestrator `ensure_transcripts_for_ticker` | — | Yes (EarningsCall + optional analysis) |

---

## Ask — Orchestrator (no LLM tools)

The orchestrator does not expose tools to Claude. It:

1. Parses intent (tickers, topics, earnings hints)
2. **Resolves company names to tickers** via the SEC public registry (`lookup_company_ticker` logic) before agents run
3. Ensures company profiles and transcripts exist
4. Runs regulations ± earnings specialists
5. Synthesizes a markdown answer

**SSE events:** `run_started`, `plan`, `agent_start` / `agent_end`, `tool_start` / `tool_end`, `message`, `answer`, `run_end`

**Frontend labels:** `frontend/src/lib/ask.ts` → `ASK_TOOL_LABELS`, `ASK_TOOLS_BY_AGENT`

---

## Regulations enrichment (not Ask)

**Module:** `backend/app/services/llm/regulatory_tools.py`  
**Used during:** `POST /api/regulations/enrich/trigger` and scheduler

Same two tools as in Ask regulations agent:

- `search_related_regulations`
- `lookup_company_profile`

These help Claude calibrate severity and tags while enriching a single raw FR document.

---

## Earnings analysis (not Ask tools)

**Module:** `backend/app/services/analysis_runner.py`

Runs four parallel LLM extractions (sentiment, hedging, guidance, topics) via `complete_json()` — not an agentic tool loop.

**Compare flow:** `comparison_runner.py` uses a single structured LLM call.

---

## HTTP APIs (user-facing, not Ask tools)

| Area | Endpoints | Role |
|------|-----------|------|
| Regulations | `GET /api/regulations`, `GET /api/regulations/{id}`, `GET /api/regulations/status`, `POST …/ingest/trigger`, `POST …/enrich/trigger` | Browse catalog, pipeline health, manual ingest/enrich |
| Impact | `GET /api/regulations/impact/by-ticker/{ticker}` | Same logic as `impact_by_ticker` tool |
| Earnings | `/api/earnings/transcripts/*`, `/api/earnings/search/*`, `/api/earnings/analysis/*` | Fetch/analyze calls; Ask tools wrap these queries |
| Ask | `POST /api/ask/stream` | SSE orchestrator |

---

## Choosing the right regulations tool (Ask)

```
User names a ticker only          → impact_by_ticker (+ lookup_company_profile)
User names severity + time/theme  → search_regulations
User names a specific rule id     → get_regulation
Simple keyword, no filters        → list_regulations or search_related_regulations
```

---

## Data dependencies

| Tool family | Needs in DB |
|-------------|-------------|
| `search_regulations` (filtered) | Ingested FR docs **+ enrichment** (severity, institution_types) |
| `list_regulations` | Ingested FR docs (enrichment optional) |
| `impact_by_ticker` | Enriched docs + company profile (auto-created or manual) |
| Earnings tools | Transcripts (+ analysis for timeline/analysis tools) |

Check pipeline health: `GET /api/regulations/status`
