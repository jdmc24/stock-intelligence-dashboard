# Regulatory Change Monitor — Product Requirements Document

**Author:** Jake McCorkle
**Last Updated:** April 1, 2026
**Status:** Pre-build
**Build Tool:** Cursor / Claude Code
**Relationship:** Module 1 of the Stock Intelligence Platform, sharing backend infrastructure with the Earnings Call Analyzer (Module 2)

---

## 1. Product Overview

A web application that monitors regulatory updates from federal financial regulators (CFPB, OCC, Federal Reserve, FDIC, SEC, FinCEN), summarizes what changed in plain language, and flags which banking products, processes, or compliance obligations are affected. Users can search, filter, and track regulatory changes over time.

The core value proposition: a compliance analyst currently spends hours reading Federal Register notices and cross-referencing them against internal policies. This tool compresses that first pass into seconds, surfacing what changed, what it means, and what it affects.

### 1.1 Why This Matters (Portfolio Framing)

For Solutions Engineering and GTM interviews, this project demonstrates:

- **End-to-end system thinking.** Scheduled data ingestion, LLM enrichment pipeline, API layer, frontend consumption. Every layer is walkable in a technical interview.
- **Financial services domain credibility.** The feature set reflects real compliance workflows at banks. You're building for a user you've actually worked alongside.
- **AI applied to a real workflow.** The LLM does structured extraction, change detection, and impact classification. Not a chatbot wrapper. Not a summarizer bolted onto a search bar.
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
- Keyword search (searches title, abstract, summary, provisions)

**Implementation:** For V1, use SQLite FTS5 (full-text search extension). Upgrade to Postgres with pg_trgm or a dedicated search index (Typesense, Meilisearch) in V2 if query volume warrants it.

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
    "medium_severity": [...],
    "low_severity": [...],
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
| POST | `/api/regulations/impact/assess` | Given a product description, identify which recent regulatory changes are relevant | Body: `{ "product_description": "..." }` |

### 4.5 System

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/regulations/status` | Ingestion pipeline health, last run time, document counts |
| POST | `/api/regulations/ingest/trigger` | Manually trigger an ingestion run (useful for demo) |
| GET | `/docs` | Auto-generated Swagger/OpenAPI docs (FastAPI built-in) |

---

## 5. Database Schema

### V1: SQLite

Two core tables plus a join table for the many-to-many tag relationships.

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

-- Indexes for common query patterns
CREATE INDEX idx_docs_pub_date ON reg_documents(publication_date);
CREATE INDEX idx_docs_type ON reg_documents(document_type);
CREATE INDEX idx_docs_status ON reg_documents(status);
CREATE INDEX idx_enrichments_severity ON reg_enrichments(severity);
CREATE INDEX idx_enrichments_effective ON reg_enrichments(effective_date);

-- Full-text search
CREATE VIRTUAL TABLE reg_documents_fts USING fts5(
    title, abstract, raw_text,
    content='reg_documents',
    content_rowid='rowid'
);
```

---

## 6. LLM Integration Details

### 6.1 Model Selection

Use `claude-sonnet-4-20250514` for all enrichment tasks. Sonnet is the right tier here: the work is structured extraction against a defined schema, not open-ended reasoning. Opus would be burning money for no quality gain.

### 6.2 Prompt Architecture

Each enrichment step gets its own prompt template stored in `backend/regulations/prompts.py`. This keeps prompts version-controlled and testable independently.

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
- Add a `/api/regulations/reprocess/{id}` endpoint (admin-only) to manually re-trigger enrichment on a specific document

---

## 7. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend | Python, FastAPI | Shared with Earnings Call Analyzer. Auto-generated API docs at `/docs`. |
| Database | SQLite + FTS5 (V1) | Simple, zero-config. FTS5 handles full-text search. Migrate to Postgres/Supabase in V2. |
| LLM | Claude API (Anthropic Python SDK) | Shared `common/llm.py` wrapper with the Earnings module. |
| Scheduling | APScheduler | In-process scheduler. Beats cron for single-process deployments. |
| Frontend | Next.js on Vercel | Matches your existing Vercel workflow and the Earnings frontend. |
| Backend hosting | Railway or Render | Simple Python hosting. Railway's free tier works for demo traffic. |
| HTTP client | `httpx` (async) | For Federal Register API calls. Async pairs well with FastAPI. |

---

## 8. Frontend Views

### 8.1 Regulatory Dashboard (Home)

- **URL:** `/regulations`
- **Layout:** Three-column density layout. Left sidebar for filters, center for document feed, right for summary stats.
- **Default view:** Most recent 20 enriched documents, sorted by publication date descending
- **Filter panel:** Agency checkboxes, document type dropdown, product area multi-select, severity pills, date range picker
- **Summary stats (right rail):** Documents processed today, this week, this month. Severity distribution donut chart. Top affected product areas bar chart.
- **Each document card shows:** Title (truncated), agency badge, publication date, severity indicator (color-coded), affected product tags, 2-sentence summary preview
- **Interaction:** Click a card to navigate to the detail view

### 8.2 Document Detail View

- **URL:** `/regulations/{id}`
- **Top section:** Full title, agency, publication date, document type badge, severity badge with rationale tooltip, link to Federal Register source
- **Summary section:** Full plain-language summary
- **Key Provisions section:** Expandable list of extracted provisions, each with CFR reference and description
- **Impact Assessment section:** Visual grid of affected products and functions (highlighted tags), institution types
- **Timeline section:** Key dates displayed horizontally: publication date, comment deadline, effective date, compliance deadline
- **Raw Text section:** Collapsible full document text with keyword highlighting

### 8.3 Daily Digest View

- **URL:** `/regulations/digest` (defaults to today) or `/regulations/digest/{date}`
- **Layout:** Newsletter-style single column
- **Organized by severity tier:** Critical/High items first with full summaries, medium items with one-line descriptions, low items listed as titles only
- **Cross-reference callouts:** "3 documents this week affecting mortgage lending" with link to filtered view
- **Navigation:** Previous/next day arrows, calendar picker

### 8.4 Impact Explorer

- **URL:** `/regulations/impact/{product}` (e.g., `/regulations/impact/mortgage_lending`)
- **Purpose:** Answer "what do I need to know about recent regulatory changes affecting my product area?"
- **Layout:** Timeline view of all documents tagged to that product, with severity-coded markers
- **Drill-down:** Click any marker to expand inline summary and provisions
- **Comparison mode:** Select two products to see overlapping regulatory requirements

### 8.5 Analytics / Trends (V2)

- **URL:** `/regulations/analytics`
- **Charts:** Agency activity over time (line chart), topic heatmap by month, severity distribution trends
- **Purpose:** Portfolio polish. Shows you can think about data beyond individual records.

### 8.6 Shared Platform Elements

The Regulatory Monitor and Earnings Call Analyzer share:

- **Navigation:** Top nav with "Regulatory Monitor" and "Earnings Analyzer" as primary sections
- **Landing page:** `/` shows a combined dashboard with recent activity from both modules
- **Design system:** Shared component library (SummaryCard, SeverityBadge, FilterPanel, SearchBar) from `frontend/src/components/`
- **Authentication:** Shared API key auth from `backend/common/auth.py`

---

## 9. Shared Infrastructure with Earnings Call Analyzer

These components live in `backend/common/` and are used by both modules:

| Component | File | What It Does |
|---|---|---|
| LLM wrapper | `common/llm.py` | Handles Claude API calls, retries, token counting, cost tracking. Both modules call `llm.analyze(prompt, text, schema)` |
| Auth | `common/auth.py` | API key validation middleware. Simple bearer token for demo purposes. |
| Models | `common/models.py` | Shared Pydantic base models (timestamps, pagination, error responses) |
| Database | `database.py` | SQLite connection management. Both modules register their tables at startup. |
| Config | `config.py` | Environment variable loading. API keys, DB path, schedule configs. |

**Router registration in `main.py`:**

```python
from fastapi import FastAPI
from backend.regulations.router import router as reg_router
from backend.earnings.router import router as earnings_router

app = FastAPI(title="Stock Intelligence Platform")
app.include_router(reg_router, prefix="/api/regulations", tags=["Regulatory Monitor"])
app.include_router(earnings_router, prefix="/api/earnings", tags=["Earnings Analyzer"])
```

This means your Swagger docs at `/docs` show both modules side by side. In an interview, you pull this up and walk through the entire platform architecture in one screen.

---

## 10. Build Phases

### Phase 1: Data Pipeline (Days 1-3)

1. Set up the FastAPI skeleton with the `/api/regulations` router
2. Build the Federal Register API client (`backend/regulations/sources.py`)
3. Write the ingestion function: fetch documents by agency, store in SQLite
4. Verify you can fetch and store 50+ documents from the past 30 days
5. Add the manual trigger endpoint (`POST /api/regulations/ingest/trigger`)

**Milestone:** Running `curl localhost:8000/api/regulations/documents` returns real Federal Register data.

### Phase 2: LLM Enrichment (Days 4-6)

1. Write prompt templates for summary, classification, impact tagging, and provisions extraction
2. Build the enrichment pipeline in `backend/regulations/service.py`
3. Process 10 stored documents, inspect outputs, iterate on prompts
4. Add enrichment data to the GET endpoints (documents now return summaries, tags, severity)
5. Add the ad-hoc analysis endpoint (`POST /api/regulations/documents/analyze`)

**Milestone:** Every stored document has structured enrichment. Prompts produce consistent, useful output.

### Phase 3: Search & Digest (Days 7-8)

1. Set up SQLite FTS5 for full-text search across titles, abstracts, and summaries
2. Add filter parameters to the documents list endpoint
3. Build the digest generation logic (aggregate enrichments by date, organize by severity)
4. Add the digest endpoints

**Milestone:** You can search "mortgage lending" and get back all relevant documents with severity-ranked results.

### Phase 4: Frontend (Days 9-12)

1. Set up the Next.js app (or add to the existing Earnings frontend if it's already scaffolded)
2. Build the Regulatory Dashboard view with filter panel and document cards
3. Build the Document Detail view
4. Build the Daily Digest view
5. Build the Impact Explorer view
6. Wire up shared navigation between Regulatory Monitor and Earnings Analyzer

**Milestone:** A complete, navigable UI that consumes your API. Demo-ready.

### Phase 5: Scheduling & Polish (Days 13-14)

1. Add APScheduler to run ingestion + enrichment daily at 6 AM ET
2. Add the `/api/regulations/status` health endpoint
3. Add API key auth (shared with Earnings module)
4. Write README with architecture diagram and setup instructions
5. Deploy backend to Railway/Render, frontend to Vercel

**Milestone:** The system runs autonomously. New regulations appear in the dashboard every morning without manual intervention.

### Phase 6: V2 Enhancements (Backlog)

- eCFR diff visualization (before/after regulatory text)
- Agency-specific feed ingestion (CFPB bulletins, OCC advisories, Fed SR letters)
- Topic trend analytics and heatmaps
- Email digest delivery (SendGrid/Resend)
- Compliance action item generation
- Cross-module linking ("this regulation mentions the same topics as JPM's recent earnings call commentary")

---

## 11. Interview Demo Script

When walking someone through this in a technical interview, the narrative arc is:

1. **Start at `/docs`.** "This is a two-module platform. Let me show you the regulatory monitor." Point to the endpoint list, explain the data model.
2. **Hit the digest endpoint.** "Here's what came out of the regulatory pipeline this morning." Show structured output, explain severity scoring.
3. **Search for a product area.** "Let's say you're a mortgage lender. Here's everything that affects you from the past 90 days." Show filtered results.
4. **Drill into a document.** Show the enrichment: summary, provisions, impact tags. "The LLM isn't just summarizing. It's classifying change type, tagging affected products, and scoring severity."
5. **Show the architecture.** "Federal Register API feeds into a FastAPI backend. Each document runs through a four-step LLM pipeline. Results are stored in SQLite with full-text search. The React frontend consumes the API."
6. **Connect to the earnings module.** "Same architecture, different data source. Together they cover the two biggest categories of unstructured information in financial services: regulatory text and earnings language."

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

---

## 13. Success Criteria

The project is demo-ready when:

1. The system ingests new Federal Register documents daily without manual intervention
2. Every document has a plain-language summary, severity score, and product/function impact tags
3. A user can search by keyword and filter by agency, product, severity, and date range
4. The daily digest endpoint returns a structured summary of recent activity
5. The Impact Explorer lets a user select "mortgage lending" and see everything relevant from the past 90 days
6. The FastAPI `/docs` page shows both the Regulatory Monitor and Earnings Analyzer endpoints side by side
7. You can walk someone through the full architecture in under 5 minutes
