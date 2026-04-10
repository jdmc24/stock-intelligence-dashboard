# Regulatory Change Monitor — Product Requirements Document

**Author:** Jake McCorkle
**Last Updated:** April 1, 2026
**Version:** 2.0
**Status:** Pre-build
**Build Tool:** Cursor / Claude Code
**Relationship:** Module 1 of the Stock Intelligence Platform, sharing backend infrastructure with the Earnings Call Analyzer (Module 2)

> **A note on module numbering:** The module numbers reflect the original product concept sequence, not build order. The Earnings Call Analyzer (Module 2) was built first. The Regulatory Monitor (Module 1) is being added to the same platform second. The numbering describes the product's logical architecture: regulations are the foundational data layer, earnings analysis sits on top. Build sequence is separate.

---

## 1. Product Overview

A web application that monitors regulatory updates from federal financial regulators (CFPB, OCC, Federal Reserve, FDIC, SEC, FinCEN), summarizes what changed in plain language, and flags which banking products, processes, or compliance obligations are affected. Users can search, filter, and track regulatory changes over time.

The core value proposition: a compliance analyst currently spends hours reading Federal Register notices and cross-referencing them against internal policies. This tool compresses that first pass into seconds, surfacing what changed, what it means, and what it affects.

**Important:** This tool provides summaries for informational purposes only and does not constitute legal, regulatory, or compliance advice. Automated tagging and severity scoring are approximations. Users should consult qualified compliance professionals before taking action based on any output.

### 1.1 Why This Matters (Portfolio Framing)

For Solutions Engineering and GTM interviews, this project demonstrates:

- **End-to-end system thinking.** Scheduled data ingestion, LLM enrichment pipeline, API layer, frontend consumption. Every layer is walkable in a technical interview.
- **Financial services domain credibility.** The feature set reflects real compliance workflows at banks. You're building for a user you've actually worked alongside.
- **AI applied to a real workflow.** The LLM does structured extraction, change detection, and impact classification.
- **API-first architecture.** FastAPI auto-generated docs at `/docs` become the interview demo. Pull it up, walk through the endpoints, explain the data model. That's a mini system design conversation.

### 1.2 Target Users (for demo narrative)

| Persona | Pain Point | What They'd Use |
|---|---|---|
| Compliance Analyst at a regional bank | Manually monitors 6+ agency feeds, triages relevance, writes internal summaries | Daily digest, impact tagging, plain-language summaries |
| Chief Compliance Officer | Needs a fast read on whether new rules require policy changes | Impact assessment by product area, severity scoring |
| Solutions Engineer selling to banks | Needs to speak credibly about regulatory pain points | The tool itself is the demo artifact. Also useful for researching prospect pain. |
| Regtech product manager | Monitors the competitive landscape of what regulators are focused on | Topic trend tracking, agency activity heatmaps |

---

## 2. Data Sources

### 2.1 Primary: Federal Register API

The Federal Register provides a free, well-documented JSON API. This is the single best structured source for regulatory updates.

- **Base URL:** `https://www.federalregister.gov/api/v1`
- **Documents endpoint:** `/documents.json?conditions[agencies][]={agency_slug}&conditions[type][]={doc_type}`
- **Agency slugs:** `consumer-financial-protection-bureau`, `comptroller-of-the-currency`, `federal-reserve-system`, `federal-deposit-insurance-corporation`, `securities-and-exchange-commission`, `financial-crimes-enforcement-network`
- **Document types to ingest:** `Rule`, `Proposed Rule`, `Notice`, `Presidential Document`
- **Pagination:** Returns 20 results per page by default, supports `per_page` (max 1000) and `page` parameters
- **Rate limits:** No published rate limits, but be respectful. 1 request per second is safe.
- **Key fields returned:** `title`, `abstract`, `document_number`, `publication_date`, `agencies`, `type`, `html_url`, `pdf_url`, `raw_text_url`, `regulation_id_numbers`, `cfr_references`, `topics`
- **Full text:** Available at `raw_text_url` for most documents. Fall back to `html_url` and scrape if raw text is unavailable.

### 2.2 Secondary: Agency-Specific Feeds

For enforcement actions, guidance letters, and bulletins that don't always hit the Federal Register:

| Agency | Source | Format | Notes |
|---|---|---|---|
| CFPB | `https://www.consumerfinance.gov/policy-compliance/rulemaking/` | HTML, RSS | Cleanest structured feeds. Start here for V1. |
| OCC | `https://www.occ.treas.gov/news-issuances/bulletins/index-bulletins.html` | HTML | Bulletins and Advisories, less structured |
| Federal Reserve | `https://www.federalreserve.gov/supervisionreg.htm` | HTML, RSS | SR Letters, policy statements |
| FDIC | `https://www.fdic.gov/regulations/laws/federal/` | HTML | FILs (Financial Institution Letters) |
| FinCEN | `https://www.fincen.gov/news-room` | HTML | Advisories, rulings, guidance |

**V1 scope:** Federal Register API only. It covers the vast majority of formal rulemaking. Agency-specific feeds are a V2 enhancement for enforcement actions and informal guidance.

### 2.3 Supplementary: CFR (Code of Federal Regulations)

For the "diff" feature (what the regulation looked like before vs. after):

- **eCFR API:** `https://www.ecfr.gov/api/versioner/v1/versions/title-{number}?part={part}`
- Returns historical versions of CFR sections
- Useful for building before/after comparisons when a final rule amends existing regulation

**V1 scope:** Store the Federal Register document text itself. eCFR diffing is a V2/V3 feature.

---

## 3. Core Features

### 3.1 Automated Regulatory Ingestion

**What it does:** A scheduled job fetches new documents from the Federal Register API daily, filters for financial services relevance, and stores raw text for downstream processing.

**Implementation details:**

- Scheduled via APScheduler (or cron if deployed on Railway/Render)
- Runs once daily at 6:00 AM ET (Federal Register publishes new documents each business day around 4:45 AM ET)
- Fetches documents from the past 24 hours for all tracked agencies
- Deduplicates against existing `document_number` values in the database
- Stores raw document metadata and full text
- Triggers LLM enrichment pipeline on new documents

**Data model (RegDocument):**

```python
class RegDocument(BaseModel):
    id: str                          # Internal UUID
    document_number: str             # Federal Register document number (unique key)
    title: str
    abstract: Optional[str]
    publication_date: date
    document_type: str               # Rule, Proposed Rule, Notice
    agencies: list[str]              # Issuing agencies
    federal_register_url: str
    pdf_url: Optional[str]
    raw_text: str                    # Full document text
    cfr_references: list[str]       # Which CFR parts are affected
    topics: list[str]               # Federal Register topic tags
    search_text: str                 # Denormalized: title + abstract + summary + provision descriptions (populated after enrichment)
    status: str                      # "raw", "processing", "enriched", "error"
    created_at: datetime
    updated_at: datetime
```

### 3.2 LLM-Powered Summarization & Enrichment

**What it does:** Each ingested document passes through a multi-step LLM analysis pipeline that produces structured, queryable metadata.

**Enrichment pipeline (sequential steps):**

**Step 1: Plain-Language Summary**
- Input: Full document text (chunked if over 8,000 tokens)
- Output: 3 to 5 sentence summary written for a compliance professional, not a lawyer
- Prompt strategy: "Summarize this regulatory document for a compliance analyst at a mid-size bank. Focus on what is changing, who it affects, and when it takes effect. Avoid legal jargon where possible."

**Step 2: Change Classification**
- Input: Full document text
- Output: Structured JSON

```json
{
    "change_type": "new_rule | amendment | proposed_rule | guidance | enforcement | withdrawal",
    "effective_date": "2026-07-01",
    "comment_deadline": "2026-05-15",
    "compliance_deadline": "2026-12-31",
    "is_final": true,
    "amends_existing": true,
    "existing_rule_reference": "12 CFR Part 1026"
}
```

**Step 3: Impact Tagging**
- Input: Full document text + summary from Step 1
- Output: Structured JSON mapping the document to affected product areas and compliance functions

```json
{
    "affected_products": ["mortgage_lending", "credit_cards", "deposit_accounts"],
    "affected_functions": ["bsa_aml", "fair_lending", "consumer_complaints", "capital_requirements"],
    "institution_types": ["commercial_bank", "credit_union", "mortgage_servicer"],
    "severity": "high",
    "severity_rationale": "Amends Reg Z disclosure requirements with a 6-month compliance window"
}
```

**Canonical product/function tags (used across the platform):**

Products: `mortgage_lending`, `credit_cards`, `auto_lending`, `student_lending`, `personal_lending`, `deposit_accounts`, `commercial_lending`, `wealth_management`, `payments`, `digital_banking`, `small_business_lending`

Functions: `bsa_aml`, `kyc_cdd`, `fair_lending`, `consumer_complaints`, `privacy`, `capital_requirements`, `liquidity`, `cybersecurity`, `vendor_management`, `model_risk`, `sanctions`

**Step 4: Key Provisions Extraction**
- Input: Full document text
- Output: List of the 3 to 7 most significant provisions or requirements, each with a one-sentence description

```json
{
    "provisions": [
        {
            "title": "Revised APR Disclosure Timing",
            "description": "Lenders must provide updated APR disclosures within 3 business days of rate lock, reduced from 7.",
            "cfr_reference": "12 CFR 1026.19(e)"
        }
    ]
}
```

**Step 5: Compliance Action Items (V2)**
- Input: Summary + impact tags + key provisions
- Output: Suggested action items for a compliance team ("Review mortgage disclosure templates," "Update APR calculation logic in LOS," "Train loan officers on new timing requirements")

**Post-enrichment: Update search index.** After all enrichment steps complete, concatenate title + abstract + summary + all provision descriptions into the `search_text` column on `reg_documents`. This denormalized column is what the FTS5 index reads from. See Section 5 for details.

**Data model (RegEnrichment):**

```python
class RegEnrichment(BaseModel):
    id: str
    document_id: str                 # FK to RegDocument
    summary: str
    change_type: str
    effective_date: Optional[date]
    comment_deadline: Optional[date]
    compliance_deadline: Optional[date]
    is_final: bool
    affected_products: list[str]
    affected_functions: list[str]
    institution_types: list[str]
    severity: str                    # "low", "medium", "high", "critical"
    severity_rationale: str
    provisions: list[dict]
    action_items: list[str]          # V2
    model_used: str                  # Track which model version produced this
    prompt_version: str              # Track prompt version for reproducibility
    processing_cost_tokens: int      # Input + output tokens consumed
    created_at: datetime
```

### 3.3 Search & Filtering

**What it does:** Users can search across all enriched regulatory documents using full-text search and faceted filters.

**Filter dimensions:**
- Agency (multi-select)
- Document type (Rule, Proposed Rule, Notice)
- Affected product area (from canonical tags)
- Affected compliance function (from canonical tags)
- Severity level
- Date range (publication date)
- Keyword search (full-text search across title, abstract, summary, and provision descriptions)

**Implementation:** SQLite FTS5 over the denormalized `search_text` column on `reg_documents`. This column is populated at the end of the enrichment pipeline by concatenating title, abstract, summary, and provision descriptions into a single searchable blob. Because the write happens at the same time as enrichment (single transaction), there's no sync problem and no need for FTS triggers or external content tables. See Section 5 for the schema.

Upgrade to Postgres with `pg_trgm` or a dedicated search index (Typesense, Meilisearch) in V2 if query volume warrants it.

### 3.4 Daily Digest

**What it does:** A generated summary of all new regulatory activity from the past 24 hours (or configurable window), organized by severity and product area.

**Output structure:**

```json
{
    "digest_date": "2026-04-01",
    "total_new_documents": 12,
    "high_severity": [
        {
            "document_id": "...",
            "title": "...",
            "summary": "...",
            "severity": "high",
            "affected_products": ["mortgage_lending"],
            "agency": "CFPB"
        }
    ],
    "medium_severity": [],
    "low_severity": [],
    "by_product": {
        "mortgage_lending": 3,
        "credit_cards": 1,
        "bsa_aml": 4
    }
}
```

**Delivery:** API endpoint returns the digest. V2 adds email delivery via SendGrid or Resend.

### 3.5 Regulatory Diff / Change Comparison (V2)

**What it does:** For rules that amend existing regulations, shows a before/after comparison of the affected CFR text.

**Implementation approach:**
- When a final rule references a CFR section, fetch the current version from the eCFR API
- After the effective date, fetch the updated version
- Run a text diff (Python `difflib` or a custom LLM-powered semantic diff)
- Display side-by-side or inline diff in the frontend

**V1 workaround:** The LLM enrichment already extracts key provisions and describes what changed. The structured diff visualization is a V2 feature.

### 3.6 Topic Trend Tracking (V2)

**What it does:** Tracks which regulatory topics are gaining or losing attention over time. Surfaces patterns like "CFPB has published 14 documents mentioning 'AI' in the past 90 days, up from 2 in the prior 90 days."

**Implementation:** Aggregate tag counts by time window. Simple time-series query against the enrichment table. Frontend visualizes as a line chart or heatmap.

### 3.7 Ticker-to-Regulatory Relevance Mapping

**What it does:** Connects a company ticker (from the Earnings Call Analyzer module) to a set of default regulatory product/function filters. This is the bridge between "show me JPM's earnings analysis" and "show me the regulations that matter to JPM."

**V1 approach: Static mapping table.** A JSON file (`company_profiles.json`) ships with 10 to 15 pre-mapped tickers for major financial institutions. Each entry maps a ticker to its relevant product areas and compliance functions from the canonical tag set.

```json
{
    "JPM": {
        "name": "JPMorgan Chase",
        "institution_types": ["commercial_bank"],
        "primary_products": ["mortgage_lending", "credit_cards", "commercial_lending", "payments", "wealth_management", "deposit_accounts"],
        "primary_functions": ["bsa_aml", "capital_requirements", "fair_lending", "cybersecurity", "model_risk", "sanctions"],
        "gics_sector": "Financials",
        "gics_sub_industry": "Diversified Banks"
    },
    "SOFI": {
        "name": "SoFi Technologies",
        "institution_types": ["commercial_bank"],
        "primary_products": ["personal_lending", "student_lending", "deposit_accounts", "digital_banking"],
        "primary_functions": ["bsa_aml", "fair_lending", "consumer_complaints", "privacy"],
        "gics_sector": "Financials",
        "gics_sub_industry": "Consumer Finance"
    }
}
```

**How it connects:**

- The Earnings Analyzer's company page (`/earnings/company/{ticker}`) gains a "Relevant Regulations" sidebar that calls `/api/regulations/impact?products={comma-separated}&functions={comma-separated}` using the ticker's mapped tags.
- The Regulatory Monitor's Impact Explorer gains a "By Company" entry point: select a ticker, and the view pre-filters to that company's relevant product areas.
- The unified home page (`/`) can show a combined feed: "Recent earnings + recent regulations for your watched companies."

**V2 approach: Inferred from earnings transcripts.** When the Earnings Analyzer processes a transcript, it already extracts topics and business segments discussed. A V2 enhancement would use those extracted topics to auto-generate the product/function mapping, so adding a new company to the Earnings Analyzer automatically populates its regulatory relevance profile. User overrides would let someone add or remove tags manually.

**V2 enrichment: NAICS/GICS classification.** Use EDGAR's company search API or a financial data API to pull GICS sector and sub-industry codes. Map GICS sub-industries to default product/function tag sets. This makes the initial mapping automated for any ticker, with manual overrides for precision.

**Data model (CompanyProfile):**

```python
class CompanyProfile(BaseModel):
    ticker: str                      # Primary key
    name: str
    institution_types: list[str]
    primary_products: list[str]      # From canonical product tags
    primary_functions: list[str]     # From canonical function tags
    gics_sector: Optional[str]
    gics_sub_industry: Optional[str]
    is_auto_generated: bool          # False for V1 static entries, True for V2 inferred
    user_overrides: Optional[dict]   # V2: manual additions/removals
    updated_at: datetime
```

---

## 4. API Endpoints

### 4.1 Documents

| Method | Endpoint | Description | Parameters |
|---|---|---|---|
| GET | `/api/regulations/documents` | List enriched documents with filters | `agency`, `type`, `product`, `function`, `severity`, `start_date`, `end_date`, `search`, `page`, `per_page` |
| GET | `/api/regulations/documents/{id}` | Full document detail with enrichment | — |
| POST | `/api/regulations/documents/analyze` | Upload raw regulatory text, get enrichment back | Body: `{ "text": "...", "title": "optional" }` |

### 4.2 Digest

| Method | Endpoint | Description | Parameters |
|---|---|---|---|
| GET | `/api/regulations/digest` | Daily digest for a given date | `date` (defaults to today), `severity_min`, `products` |
| GET | `/api/regulations/digest/weekly` | Weekly rollup | `week_of` (ISO date of Monday) |

### 4.3 Analytics

| Method | Endpoint | Description | Parameters |
|---|---|---|---|
| GET | `/api/regulations/analytics/by-agency` | Document counts by agency over time | `start_date`, `end_date`, `granularity` (day/week/month) |
| GET | `/api/regulations/analytics/by-product` | Document counts by affected product | Same as above |
| GET | `/api/regulations/analytics/by-topic` | Topic frequency trends | Same as above |
| GET | `/api/regulations/analytics/severity-distribution` | Severity breakdown for a time period | `start_date`, `end_date` |

### 4.4 Impact Assessment

| Method | Endpoint | Description | Parameters |
|---|---|---|---|
| GET | `/api/regulations/impact` | All recent changes affecting a given product or function | `product`, `function`, `lookback_days` (default 90) |
| GET | `/api/regulations/impact/by-ticker/{ticker}` | All recent changes relevant to a company, using its mapped product/function profile | `lookback_days` (default 90) |
| POST | `/api/regulations/impact/assess` | Given a product description, identify which recent regulatory changes are relevant | Body: `{ "product_description": "..." }` |

### 4.5 Company Profiles (Cross-Module)

| Method | Endpoint | Description | Parameters |
|---|---|---|---|
| GET | `/api/companies` | List all company profiles | — |
| GET | `/api/companies/{ticker}` | Get a company's regulatory relevance profile | — |
| PUT | `/api/companies/{ticker}` | Update a company's tag overrides (V2) | Body: `{ "add_products": [...], "remove_products": [...], ... }` |

### 4.6 System

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/regulations/status` | Ingestion pipeline health, last run time, document counts |
| POST | `/api/regulations/ingest/trigger` | Manually trigger an ingestion run (useful for demo) |
| POST | `/api/regulations/reprocess/{id}` | Re-trigger enrichment on a specific document (admin-only) |
| GET | `/docs` | Auto-generated Swagger/OpenAPI docs (FastAPI built-in) |

---

## 5. Database Schema

### V1: SQLite

Three core tables. Full-text search uses a denormalized `search_text` column on `reg_documents` to avoid cross-table FTS complexity.

**Design decision: denormalized search.** The PRD calls for keyword search across title, abstract, summary, and provision descriptions. Summary and provisions live on `reg_enrichments`, not `reg_documents`. Rather than maintaining a second FTS table or adding triggers to keep an external content FTS table in sync, we add a `search_text` column to `reg_documents` that gets populated at the end of the enrichment pipeline. The enrichment service concatenates `title + abstract + summary + provision_descriptions` into this column in the same transaction that writes the enrichment record. One column, one FTS table, no sync issues.

```sql
CREATE TABLE reg_documents (
    id TEXT PRIMARY KEY,
    document_number TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    publication_date DATE NOT NULL,
    document_type TEXT NOT NULL,
    agencies TEXT NOT NULL,              -- JSON array
    federal_register_url TEXT NOT NULL,
    pdf_url TEXT,
    raw_text TEXT NOT NULL,
    cfr_references TEXT,                 -- JSON array
    fr_topics TEXT,                      -- JSON array (Federal Register's own topic tags)
    search_text TEXT,                    -- Denormalized: title + abstract + summary + provision descriptions. NULL until enrichment completes.
    status TEXT NOT NULL DEFAULT 'raw',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reg_enrichments (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES reg_documents(id),
    summary TEXT NOT NULL,
    change_type TEXT NOT NULL,
    effective_date DATE,
    comment_deadline DATE,
    compliance_deadline DATE,
    is_final BOOLEAN,
    affected_products TEXT NOT NULL,      -- JSON array
    affected_functions TEXT NOT NULL,     -- JSON array
    institution_types TEXT NOT NULL,      -- JSON array
    severity TEXT NOT NULL,
    severity_rationale TEXT,
    provisions TEXT NOT NULL,             -- JSON array of objects
    action_items TEXT,                    -- JSON array (V2)
    model_used TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    processing_cost_tokens INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id)
);

CREATE TABLE reg_digests (
    id TEXT PRIMARY KEY,
    digest_date DATE UNIQUE NOT NULL,
    total_documents INTEGER NOT NULL,
    high_severity_count INTEGER DEFAULT 0,
    content TEXT NOT NULL,               -- Full digest JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE company_profiles (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    institution_types TEXT NOT NULL,      -- JSON array
    primary_products TEXT NOT NULL,       -- JSON array
    primary_functions TEXT NOT NULL,      -- JSON array
    gics_sector TEXT,
    gics_sub_industry TEXT,
    is_auto_generated BOOLEAN DEFAULT FALSE,
    user_overrides TEXT,                  -- JSON object (V2)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX idx_docs_pub_date ON reg_documents(publication_date);
CREATE INDEX idx_docs_type ON reg_documents(document_type);
CREATE INDEX idx_docs_status ON reg_documents(status);
CREATE INDEX idx_enrichments_severity ON reg_enrichments(severity);
CREATE INDEX idx_enrichments_effective ON reg_enrichments(effective_date);

-- Full-text search over denormalized search_text column
-- Simple FTS5 table (not external content). Populated by inserting rows
-- after enrichment completes. Avoids trigger complexity.
CREATE VIRTUAL TABLE reg_search_fts USING fts5(
    document_id,
    search_text
);
```

**FTS population (in the enrichment service):**

```python
# After writing enrichment record, in the same transaction:
search_text = " ".join([
    doc.title,
    doc.abstract or "",
    enrichment.summary,
    " ".join(p["description"] for p in enrichment.provisions)
])

# Update the denormalized column
db.execute(
    "UPDATE reg_documents SET search_text = ?, status = 'enriched', updated_at = ? WHERE id = ?",
    (search_text, now, doc.id)
)

# Insert into FTS index
db.execute(
    "INSERT INTO reg_search_fts (document_id, search_text) VALUES (?, ?)",
    (doc.id, search_text)
)
```

**On re-enrichment** (when prompts are updated and a document is reprocessed): delete the old FTS row and insert a new one in the same transaction. The `reprocess` endpoint handles this.

---

## 6. LLM Integration Details

### 6.1 Model Selection

Use `claude-sonnet-4-20250514` for all enrichment tasks. Sonnet is the right tier: the work is structured extraction against a defined schema. Opus would be burning tokens for no quality gain on this type of task.

**Important:** The model ID should be a single shared constant in `config.py` (e.g., `LLM_MODEL_ID`), referenced by both the Regulatory Monitor and Earnings Call Analyzer modules. When Anthropic publishes a new model version, update the constant in one place.

```python
# config.py
LLM_MODEL_ID = "claude-sonnet-4-20250514"  # Verify against Anthropic API docs at implementation time
```

### 6.2 Prompt Architecture

Each enrichment step gets its own prompt template stored in `regulations/prompts.py`. This keeps prompts version-controlled and testable independently.

**Prompt design principles:**

- **Structured output only.** Every prompt requests JSON. Include the exact schema in the prompt with field descriptions and allowed values.
- **Few-shot examples.** Include 2 to 3 examples of input/output pairs in each prompt. Use real Federal Register document excerpts (they're public domain).
- **Grounding instructions.** "Only tag products that are explicitly mentioned or directly implicated. Do not tag tangentially related products." Prevents over-tagging.
- **Severity calibration.** Include explicit definitions for each severity level:
  - `critical`: Requires immediate compliance action, short deadline, broad impact
  - `high`: Significant operational change required, affects multiple product lines or functions
  - `medium`: Requires policy review but not operational overhaul
  - `low`: Informational, minor clarification, or does not require action

### 6.3 Chunking Strategy

Federal Register documents range from 500 words (simple notices) to 50,000+ words (major rulemakings like the CFPB's 1071 rule). Strategy:

- **Under 6,000 tokens:** Process the full document in a single call for each enrichment step.
- **6,000 to 15,000 tokens:** Process full text for summary and classification. Chunk for provisions extraction (split by section headers, process each chunk, aggregate).
- **Over 15,000 tokens:** Chunk the document into sections. Run summary on each section, then run a final consolidation prompt that takes section summaries as input and produces the overall summary, classification, and impact tags.

### 6.4 Cost Estimation

Most Federal Register documents relevant to bank compliance are 2,000 to 8,000 words. Assuming an average of ~6,000 tokens input per document:

- Summary: ~6K in + 500 out
- Classification: ~6K in + 300 out
- Impact tagging: ~7K in (includes summary) + 400 out
- Provisions: ~6K in + 1K out

**Rough total per document: ~25K tokens in, ~2.2K tokens out.**

At Sonnet rates, that's roughly $0.10 to $0.15 per document. Even processing 50 new documents per day costs under $8/day. Well within personal project territory.

### 6.5 Error Handling & Retry Logic

- If the LLM returns malformed JSON, retry once with a "your previous response was not valid JSON" follow-up
- If retry also fails, mark the document status as `error` and log the raw response for debugging
- Track `model_used` and `prompt_version` on every enrichment record so you can re-run processing when you update prompts
- The `/api/regulations/reprocess/{id}` endpoint (admin-only) re-triggers enrichment on a specific document, deletes the old FTS row, and inserts the updated one

---

## 7. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend | Python, FastAPI | Shared with Earnings Call Analyzer. Auto-generated API docs at `/docs`. |
| Database | SQLite + FTS5 (V1) | Simple, zero-config. FTS5 handles full-text search via denormalized column. Migrate to Postgres/Supabase in V2. |
| LLM | Claude API (Anthropic Python SDK) | Shared `common/llm.py` wrapper with the Earnings module. Model ID constant in `config.py`. |
| Scheduling | APScheduler | In-process scheduler. Beats cron for single-process deployments. |
| Frontend | Next.js on Vercel | Matches your existing Vercel workflow and the Earnings frontend. |
| Backend hosting | Railway or Render | Simple Python hosting. Railway's free tier works for demo traffic. |
| HTTP client | `httpx` (async) | For Federal Register API calls. Async pairs well with FastAPI. |

---

## 8. Project Structure & Import Paths

> **Alignment note:** The folder layout below is a reference architecture. Before scaffolding, check the existing Earnings Call Analyzer repo structure and align import paths accordingly. If the earnings module uses `app/earnings/...` rather than `earnings/...`, mirror that pattern here. The PRD uses short-form paths for readability. The important thing is that both modules follow the same convention.

```
fs-intel-platform/
│
├── main.py                      # FastAPI app entry point, mounts both routers
├── config.py                    # Shared: API keys, DB path, LLM_MODEL_ID, schedule configs
├── database.py                  # Shared: SQLite connection, table registration
│
├── common/                      # Shared utilities
│   ├── llm.py                   # Claude API wrapper (analyze, retry, token counting)
│   ├── auth.py                  # API key validation middleware
│   └── models.py                # Shared Pydantic base models (pagination, errors, timestamps)
│
├── regulations/                 # Regulatory Monitor module
│   ├── router.py                # /api/regulations/* endpoints
│   ├── models.py                # RegDocument, RegEnrichment, RegDigest
│   ├── service.py               # Ingestion, enrichment pipeline, search_text population, FTS writes
│   ├── sources.py               # Federal Register API client
│   └── prompts.py               # LLM prompt templates (versioned)
│
├── earnings/                    # Earnings Call Analyzer module (already exists)
│   ├── router.py
│   ├── models.py
│   ├── service.py
│   ├── sources.py
│   └── prompts.py
│
├── companies/                   # Cross-module: company profiles and ticker mapping
│   ├── router.py                # /api/companies/* endpoints
│   ├── models.py                # CompanyProfile
│   ├── service.py               # Profile lookup, tag resolution
│   └── company_profiles.json    # V1 static mapping file
│
├── data/                        # Local storage (gitignored)
│   ├── fs_intel.db              # SQLite database
│   └── raw/                     # Cached raw documents
│
├── frontend/                    # Next.js app (Vercel deployment)
│   └── src/
│       ├── app/
│       │   ├── page.tsx                    # Unified home
│       │   ├── regulations/
│       │   │   ├── page.tsx                # Regulatory Dashboard
│       │   │   ├── [id]/page.tsx           # Document Detail
│       │   │   ├── digest/page.tsx         # Daily Digest
│       │   │   └── impact/[product]/page.tsx # Impact Explorer
│       │   ├── earnings/                   # (already exists)
│       │   └── company/[ticker]/page.tsx   # Company view (both modules)
│       └── components/
│           ├── SummaryCard.tsx             # Shared
│           ├── SeverityBadge.tsx           # Shared
│           ├── FilterPanel.tsx            # Shared
│           ├── SearchBar.tsx              # Shared
│           └── DisclaimerFooter.tsx        # "Not legal/compliance advice"
│
├── requirements.txt
├── .env                         # API keys (never committed)
└── README.md
```

**Router registration in `main.py`:**

```python
from fastapi import FastAPI
from regulations.router import router as reg_router
from earnings.router import router as earnings_router
from companies.router import router as companies_router

app = FastAPI(title="Stock Intelligence Platform")
app.include_router(reg_router, prefix="/api/regulations", tags=["Regulatory Monitor"])
app.include_router(earnings_router, prefix="/api/earnings", tags=["Earnings Analyzer"])
app.include_router(companies_router, prefix="/api/companies", tags=["Company Profiles"])
```

---

## 9. Frontend Views

### 9.1 Unified Home (`/`)

**Purpose:** Single landing page for the Stock Intelligence Platform showing recent activity from both modules.

**Layout:**
- **Header:** Platform name, top nav with "Regulations" and "Earnings" links, search bar (routes to appropriate module based on query type)
- **Left column: Regulatory highlights.** 3 to 5 most recent high-severity regulatory documents with summary previews. "View all" link to `/regulations`.
- **Right column: Earnings highlights.** 3 to 5 most recent earnings analyses with sentiment indicators. "View all" link to `/earnings`.
- **Bottom section: Watchlist (V2).** If the user has watched tickers, show a combined feed of "recent earnings + recent relevant regulations" for those companies.
- **Footer:** Non-reliance disclaimer: "This tool provides summaries for informational purposes only and does not constitute legal, regulatory, or compliance advice."

### 9.2 Regulatory Dashboard

- **URL:** `/regulations`
- **Layout:** Three-column density layout. Left sidebar for filters, center for document feed, right for summary stats.
- **Default view:** Most recent 20 enriched documents, sorted by publication date descending
- **Filter panel:** Agency checkboxes, document type dropdown, product area multi-select, severity pills, date range picker
- **Summary stats (right rail):** Documents processed today, this week, this month. Severity distribution donut chart. Top affected product areas bar chart.
- **Each document card shows:** Title (truncated), agency badge, publication date, severity indicator (color-coded), affected product tags, 2-sentence summary preview
- **Interaction:** Click a card to navigate to the detail view

### 9.3 Document Detail View

- **URL:** `/regulations/{id}`
- **Top section:** Full title, agency, publication date, document type badge, severity badge with rationale tooltip, link to Federal Register source
- **Summary section:** Full plain-language summary
- **Key Provisions section:** Expandable list of extracted provisions, each with CFR reference and description
- **Impact Assessment section:** Visual grid of affected products and functions (highlighted tags), institution types
- **Timeline section:** Key dates displayed horizontally: publication date, comment deadline, effective date, compliance deadline
- **Raw Text section:** Collapsible full document text with keyword highlighting

### 9.4 Daily Digest View

- **URL:** `/regulations/digest` (defaults to today) or `/regulations/digest/{date}`
- **Layout:** Newsletter-style single column
- **Organized by severity tier:** Critical/High items first with full summaries, medium items with one-line descriptions, low items listed as titles only
- **Cross-reference callouts:** "3 documents this week affecting mortgage lending" with link to filtered view
- **Navigation:** Previous/next day arrows, calendar picker

### 9.5 Impact Explorer

- **URL:** `/regulations/impact/{product}` (e.g., `/regulations/impact/mortgage_lending`)
- **Purpose:** Answer "what do I need to know about recent regulatory changes affecting my product area?"
- **Layout:** Timeline view of all documents tagged to that product, with severity-coded markers
- **Drill-down:** Click any marker to expand inline summary and provisions
- **Comparison mode:** Select two products to see overlapping regulatory requirements
- **By-company entry point:** `/regulations/impact/company/{ticker}` pre-filters using the ticker's mapped product/function tags from the company profile

### 9.6 Company View (Cross-Module)

- **URL:** `/company/{ticker}` (e.g., `/company/JPM`)
- **Purpose:** Unified view of everything the platform knows about a company, bridging both modules
- **Left column: Earnings.** Most recent transcript analysis, sentiment trend sparkline, link to full earnings history
- **Right column: Regulations.** Recent regulatory changes relevant to this company's product mix (filtered via company profile tags), severity distribution
- **Company profile sidebar:** Shows which product/function tags are mapped to this ticker. V2 adds edit controls.

### 9.7 Analytics / Trends (V2)

- **URL:** `/regulations/analytics`
- **Charts:** Agency activity over time (line chart), topic heatmap by month, severity distribution trends
- **Purpose:** Portfolio polish. Shows you can think about data beyond individual records.

### 9.8 Shared Platform Elements

The Regulatory Monitor and Earnings Call Analyzer share:

- **Navigation:** Top nav with "Home," "Regulations," "Earnings," and company search
- **Design system:** Shared component library (SummaryCard, SeverityBadge, FilterPanel, SearchBar, DisclaimerFooter)
- **Authentication:** Shared API key auth from `common/auth.py`
- **Disclaimer footer:** Present on every page. "This tool provides summaries for informational purposes only and does not constitute legal, regulatory, or compliance advice."

---

## 10. Build Phases

### Phase 1: Data Pipeline (Days 1-3)

1. Set up the FastAPI skeleton with the `/api/regulations` router (align import paths with existing earnings repo structure)
2. Add `LLM_MODEL_ID` constant to `config.py` (verify model string against Anthropic API docs)
3. Build the Federal Register API client (`regulations/sources.py`)
4. Write the ingestion function: fetch documents by agency, store in SQLite
5. Verify you can fetch and store 50+ documents from the past 30 days
6. Add the manual trigger endpoint (`POST /api/regulations/ingest/trigger`)

**Milestone:** Running `curl localhost:8000/api/regulations/documents` returns real Federal Register data.

### Phase 2: LLM Enrichment (Days 4-6)

1. Write prompt templates for summary, classification, impact tagging, and provisions extraction
2. Build the enrichment pipeline in `regulations/service.py`
3. Add `search_text` population at the end of the enrichment pipeline (concatenate title + abstract + summary + provision descriptions)
4. Set up FTS5 index on `search_text` and write FTS insert logic in the same transaction as enrichment writes
5. Process 10 stored documents, inspect outputs, iterate on prompts
6. Add enrichment data to the GET endpoints (documents now return summaries, tags, severity)
7. Add the ad-hoc analysis endpoint (`POST /api/regulations/documents/analyze`)

**Milestone:** Every stored document has structured enrichment. FTS index is populated. Prompts produce consistent, useful output.

### Phase 3: Search & Digest (Days 7-8)

1. Wire up FTS5 queries in the documents list endpoint (`search` parameter triggers FTS match against `reg_search_fts`)
2. Add faceted filter parameters (agency, type, product, function, severity, date range)
3. Build the digest generation logic (aggregate enrichments by date, organize by severity)
4. Add the digest endpoints
5. Add the reprocess endpoint with FTS row cleanup

**Milestone:** You can search "mortgage lending" and get back all relevant documents with severity-ranked results. FTS correctly searches across document metadata and enrichment content.

### Phase 4: Company Profiles & Cross-Module Wiring (Days 9-10)

1. Create `company_profiles.json` with 10 to 15 major FS tickers pre-mapped
2. Build the `/api/companies` router and endpoints
3. Add the `company_profiles` table to the database
4. Build the `/api/regulations/impact/by-ticker/{ticker}` endpoint
5. Wire company profile tags into the Impact Explorer's by-company entry point

**Milestone:** Hitting `/api/regulations/impact/by-ticker/JPM` returns all recent regulatory changes relevant to JPMorgan's product mix.

### Phase 5: Frontend (Days 11-14)

1. Build the unified home page (`/`) with highlights from both modules
2. Build the Regulatory Dashboard view with filter panel and document cards
3. Build the Document Detail view
4. Build the Daily Digest view
5. Build the Impact Explorer view (including by-company entry point)
6. Build the Company View page (`/company/{ticker}`) bridging both modules
7. Add DisclaimerFooter component to all pages
8. Wire up shared navigation between all sections

**Milestone:** A complete, navigable UI that consumes your API. Demo-ready.

### Phase 6: Scheduling & Polish (Days 15-16)

1. Add APScheduler to run ingestion + enrichment daily at 6 AM ET
2. Add the `/api/regulations/status` health endpoint
3. Add API key auth (shared with Earnings module)
4. Write README with architecture diagram and setup instructions
5. Deploy backend to Railway/Render, frontend to Vercel

**Milestone:** The system runs autonomously. New regulations appear in the dashboard every morning without manual intervention.

### Phase 7: V2 Enhancements (Backlog)

- eCFR diff visualization (before/after regulatory text)
- Agency-specific feed ingestion (CFPB bulletins, OCC advisories, Fed SR letters)
- Topic trend analytics and heatmaps
- Email digest delivery (SendGrid/Resend)
- Compliance action item generation
- Auto-generated company profiles from GICS codes and earnings transcript topics
- User-editable tag overrides on company profiles
- Company watchlist with combined regulatory + earnings feed
- Cross-module linking ("this regulation mentions the same topics as JPM's recent earnings call commentary")

---

## 11. Interview Demo Script

When walking someone through this in a technical interview, the narrative arc is:

1. **Start at `/docs`.** "This is a two-module platform. Let me show you the regulatory monitor." Point to the endpoint list, explain the data model. Note the Company Profiles section that bridges both modules.
2. **Hit the digest endpoint.** "Here's what came out of the regulatory pipeline this morning." Show structured output, explain severity scoring.
3. **Search for a product area.** "Let's say you're a mortgage lender. Here's everything that affects you from the past 90 days." Show filtered results. Mention that search works across both the raw document text and the LLM-generated summaries.
4. **Drill into a document.** Show the enrichment: summary, provisions, impact tags. "The LLM is classifying change type, tagging affected products, and scoring severity. Each of those is a separate prompt with its own schema."
5. **Show a company view.** "Here's JPMorgan. On the left, recent earnings analysis. On the right, regulatory changes that matter to their business mix. The platform connects these through a product tag mapping."
6. **Show the architecture.** "Federal Register API feeds into a FastAPI backend. Each document runs through a four-step LLM pipeline. Results are stored in SQLite with full-text search over a denormalized index. The React frontend consumes the API."
7. **Connect to the earnings module.** "Same architecture, different data source. Together they cover the two biggest categories of unstructured information in financial services: regulatory text and earnings language."

---

## 12. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Federal Register API changes or goes down | Low | Cache raw responses. The API has been stable for years. |
| LLM produces inconsistent severity scores | Medium | Anchor prompts with explicit severity definitions and few-shot examples. Log all outputs for review. Add a "confidence" field. |
| Over-tagging (everything tagged as "high" severity) | Medium | Include negative examples in prompts. "This notice is low severity because..." |
| Document text too long for single LLM call | Medium | Chunking strategy defined in Section 6.3. Test with the longest documents early. |
| SQLite performance at scale | Low (for demo) | You'll have hundreds of documents, not millions. SQLite handles this easily. Postgres is the V2 path if needed. |
| Scope creep into V2 features during build | High | Stick to the phase plan. The diff visualization and email digest are tempting but not needed for a demo-ready product. |
| Users misinterpret automated tagging as compliance advice | Medium | Non-reliance disclaimer on every page and in API response metadata. Severity scores include rationale text. |
| Import path misalignment with existing earnings repo | Medium | Check the earnings repo structure before scaffolding. Align conventions in Phase 1, Day 1. |

---

## 13. Success Criteria

The project is demo-ready when:

1. The system ingests new Federal Register documents daily without manual intervention
2. Every document has a plain-language summary, severity score, and product/function impact tags
3. A user can search by keyword (across document text, summaries, and provisions) and filter by agency, product, severity, and date range
4. The daily digest endpoint returns a structured summary of recent activity
5. The Impact Explorer lets a user select "mortgage lending" and see everything relevant from the past 90 days
6. The Impact Explorer supports a by-company entry point using ticker-mapped product/function tags
7. The unified home page shows highlights from both modules
8. The Company View page bridges earnings analysis and regulatory relevance for a given ticker
9. The FastAPI `/docs` page shows Regulatory Monitor, Earnings Analyzer, and Company Profile endpoints side by side
10. A non-reliance disclaimer appears on every frontend page and in API metadata
11. You can walk someone through the full architecture in under 5 minutes
