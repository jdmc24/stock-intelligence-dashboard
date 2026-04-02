# Earnings Call Analyzer — Product Requirements Document

**Author:** Jake McCorkle
**Last Updated:** March 31, 2026
**Status:** Pre-build
**Build Tool:** Cursor / Claude Code

---

## 1. Product Overview

A web application that ingests public earnings call transcripts and uses LLM analysis to surface sentiment shifts, management hedging language, forward-looking guidance, and key metric callouts. Users can track how executive tone and commitments evolve quarter over quarter for any publicly traded company.

This is the second module of the FS Intelligence Platform (the first being the Regulatory Change Monitor). Both share a thesis: AI tools that help financial services professionals make sense of unstructured data.

### 1.1 Why This Matters (Portfolio Framing)

For Solutions Engineering and GTM interviews, this project demonstrates:

- **System design fluency.** Backend API, data pipeline, LLM integration, frontend consumption. Walkable architecture.
- **Domain depth.** Financial services professionals are the target user. The feature set reflects real analyst workflows.
- **AI product sense.** The LLM is doing meaningful extraction and comparison, not just summarization. Shows you understand where AI adds leverage versus where it adds noise.
- **Interviewable surface area.** Every component (data sourcing, prompt engineering, API design, UX decisions) is a conversation starter.

### 1.2 Target Users (for demo narrative)

| Persona | Pain Point | What They'd Use |
|---|---|---|
| Equity Research Analyst | Reads 20+ transcripts per earnings season manually | Sentiment trends, hedging detection, quarter-over-quarter comparison |
| Portfolio Manager | Needs fast signal on whether management tone is shifting | Forward-looking guidance extraction, confidence scoring |
| Sales Engineer at a FinTech | Preparing for a pitch to a bank's CFO office | Company-specific talking points pulled from recent earnings |

---

## 2. Data Sources

### 2.1 Primary: EarningsCall.biz API

EarningsCall.biz provides a purpose-built API and SDK for accessing earnings call transcripts. It covers 5,000+ publicly traded companies with transcripts segmented by speaker, including prepared remarks and Q&A sections.

**Why EarningsCall over alternatives:**

SEC EDGAR 8-K filings rarely contain the full transcript text. API Ninjas and Financial Modeling Prep both gate transcript access behind paid tiers with less developer-friendly SDKs. EarningsCall has native Python and JavaScript libraries, pre-segmented speaker data, and free access to Apple and Microsoft transcripts for development.

**Python SDK:**

```bash
pip install earningscall
```

```python
from earningscall import get_company

company = get_company("aapl")
transcript = company.get_transcript(year=2025, quarter=3)

# Basic: transcript.text (full transcript as string)
# Enhanced (paid tier): transcript.speakers[] with speaker name, title, text, and is_qa flag
```

**Key endpoints/methods:**

| Method | What It Does |
|---|---|
| `get_company(ticker)` | Look up a company by ticker symbol |
| `company.get_transcript(year, quarter)` | Fetch transcript for a specific quarter |
| `company.get_transcript(year, quarter, level=2)` | Enhanced: speaker-segmented transcript |
| `company.get_transcript(year, quarter, level=3)` | Enhanced: word-level timestamps |
| `get_all_companies()` | List all available companies with sector/industry metadata |

**Data tiers:**

| Tier | What You Get |
|---|---|
| Free (no API key) | Apple and Microsoft transcripts only. Sufficient for development and testing. |
| Basic (API key) | 5,000+ companies, full transcript text as a single string |
| Enhanced (paid) | Speaker segmentation (name, title, text), prepared remarks vs. Q&A separation, word-level timestamps |

**Development strategy:** Build and test the full analysis pipeline using the free Apple and Microsoft transcripts. Two companies across multiple quarters is enough to validate sentiment analysis, hedging detection, guidance extraction, and quarter-over-quarter comparison. Upgrade to a paid tier when ready to demo with broader company coverage.

### 2.2 Secondary: Manual Upload

Support a manual upload path where users can paste or upload a raw transcript file. This serves two purposes: it unblocks development if the API is unavailable, and it lets users analyze transcripts from companies not covered by EarningsCall (e.g., smaller international companies that post transcripts on their IR pages).

Accepted formats: plain text (.txt), PDF (.pdf), or paste directly into the UI.

### 2.3 Tertiary: Financial Data APIs (V2)

For enriching analysis with actual reported numbers (revenue, EPS, guidance figures):

| Source | What It Provides |
|---|---|
| Alpha Vantage (free tier) | Earnings data, company overview |
| Financial Modeling Prep (free tier) | Income statements, earnings surprises |
| SEC XBRL API | Structured financial data from filings |

For V1, the LLM extracts numbers mentioned in the transcript text. Structured financial APIs are a V2 enhancement for validating LLM-extracted figures against reported actuals.

---

## 3. Core Features

### 3.1 Transcript Ingestion & Processing

**What it does:** User provides a company ticker (or uploads a raw transcript). The system fetches the most recent earnings call transcript via the EarningsCall SDK, which returns pre-structured data, and stores it for analysis.

**Transcript structure (provided by EarningsCall Enhanced tier):**

```
- Speaker segments with name, title, and text
- is_qa flag distinguishing prepared remarks from Q&A
- Speaker type: management, investor, or operator
```

For manual uploads (plain text or PDF), the system uses LLM-based parsing to segment the transcript into the same structure.

**Processing pipeline:**

```
API fetch (EarningsCall SDK)
  → Pre-structured speaker segments (name, title, text, is_qa)
  → Paragraph chunking (for granular analysis)
  → LLM enrichment (see 3.2 through 3.5)
  → Structured storage

Manual upload (fallback)
  → LLM-based section segmentation (prepared remarks / Q&A)
  → LLM-based speaker identification (map names to roles)
  → Paragraph chunking
  → LLM enrichment
  → Structured storage
```

### 3.2 Sentiment Analysis

**What it does:** Scores the overall tone of the call and breaks it down by speaker, section, and topic. Goes beyond simple positive/negative to capture nuance.

**Sentiment dimensions:**

| Dimension | What It Captures | Example Signal |
|---|---|---|
| Confidence | How certain is management about their outlook? | "We are confident" vs. "We hope to" |
| Defensiveness | Are they deflecting or directly addressing concerns? | Pivot language, blame-shifting to macro conditions |
| Specificity | Are they giving concrete numbers or staying vague? | "We expect 12% growth" vs. "We expect continued momentum" |
| Urgency | How pressing do they frame current conditions? | "Immediately" vs. "over time" |

**Output format (per section/speaker):**

```json
{
  "speaker": "Jane Smith, CFO",
  "section": "prepared_remarks",
  "sentiment": {
    "overall": "cautiously_optimistic",
    "confidence": 0.72,
    "defensiveness": 0.31,
    "specificity": 0.65,
    "urgency": 0.44
  },
  "notable_quotes": [
    {
      "text": "We're seeing early signs of stabilization in our commercial book",
      "signal": "hedged_positive",
      "context": "Follows a quarter where commercial lending was flagged as a concern"
    }
  ]
}
```

### 3.3 Hedging Language Detection

**What it does:** Flags instances where executives use language that softens, qualifies, or walks back commitments. This is the highest-signal feature for analysts. When a CEO shifts from "we will" to "we expect to" on a specific initiative, that tells you something.

**Hedging categories:**

- **Qualifier injection:** "largely," "substantially," "to a degree"
- **Tense shifts:** Future certain ("we will") to future uncertain ("we anticipate")
- **Conditional framing:** "Subject to," "assuming," "barring any"
- **Attribution deflection:** Blaming macro, regulatory, or market conditions for outcomes
- **Scope narrowing:** "In certain markets" when previously the claim was broad

**Output format:**

```json
{
  "hedging_instances": [
    {
      "text": "We continue to expect growth, subject to macroeconomic conditions",
      "category": "conditional_framing",
      "severity": "moderate",
      "prior_quarter_comparison": "Q2 statement was 'We expect strong growth in the second half'",
      "delta": "Added macro caveat, removed 'strong' qualifier"
    }
  ],
  "hedging_score": 0.58,
  "hedging_trend": "increasing"
}
```

### 3.4 Forward-Looking Guidance Extraction

**What it does:** Pulls out every forward-looking statement and structures it: what metric, what direction, what timeframe, how confident.

**Fields to extract per guidance statement:**

- **Metric:** Revenue, EPS, margin, headcount, capex, specific product line
- **Direction:** Up, down, flat, range-bound
- **Magnitude:** Specific number, percentage, or qualitative ("modest," "significant")
- **Timeframe:** Next quarter, full year, medium-term, unspecified
- **Confidence language:** How firmly stated
- **Conditions:** Any caveats attached
- **Prior guidance:** What was said last quarter on the same metric (if available)

### 3.5 Quarter-Over-Quarter Comparison

**What it does:** The killer feature. Compares two or more transcripts from the same company across quarters and highlights what changed in tone, language, and commitments.

**Comparison dimensions:**

- Topics that appeared in Q(n) but not Q(n-1), and vice versa
- Sentiment shift per topic (e.g., "AI investment" went from confident to cautious)
- Guidance changes (raised, lowered, maintained, withdrew)
- New hedging language that wasn't present before
- Q&A pressure points: which analyst questions drew the most defensive responses
- Executive speaking time shifts (if CFO suddenly talks twice as long about credit quality, that's a signal)

**Output format:**

```json
{
  "company": "JPM",
  "quarters_compared": ["Q3-2025", "Q4-2025"],
  "key_shifts": [
    {
      "topic": "AI Investment",
      "q3_tone": "aggressive_expansion",
      "q4_tone": "measured_optimism",
      "evidence": "Q3: 'We're investing heavily and see immediate returns.' Q4: 'We continue to invest thoughtfully as we evaluate ROI.'",
      "interpretation": "Shift from conviction to evaluation mode. Possible budget pressure or early results underperforming expectations."
    }
  ],
  "new_topics": ["Regulatory capital requirements"],
  "dropped_topics": ["Branch expansion"],
  "guidance_changes": [
    {
      "metric": "Net Interest Income",
      "q3_guidance": "$88-89B",
      "q4_guidance": "$87-88B",
      "change": "lowered",
      "language_shift": "From 'comfortable with' to 'current expectations suggest'"
    }
  ]
}
```

### 3.6 Topic Extraction & Tagging

**What it does:** Identifies the key topics discussed in each call, maps them to standardized financial services categories, and tracks topic frequency across calls.

**Standard topic taxonomy (financial services):**

```
Credit Quality, Net Interest Margin, Fee Income, Capital Ratios,
Regulatory/Compliance, Technology/AI Investment, Headcount/Efficiency,
Commercial Lending, Consumer Lending, Wealth Management, Trading/Markets,
M&A Activity, Share Buybacks/Dividends, Deposit Growth, Digital Banking,
Cybersecurity, ESG/Climate, Macroeconomic Outlook
```

---

## 4. API Design

Base URL: `/api/earnings`

### 4.1 Transcript Management

| Method | Endpoint | Description |
|---|---|---|
| POST | `/transcripts/fetch` | Fetch transcript for a ticker via EarningsCall API |
| POST | `/transcripts/upload` | Upload a raw transcript (paste or file) |
| GET | `/transcripts` | List all stored transcripts, filterable by company/date |
| GET | `/transcripts/{id}` | Get a specific transcript with parsed sections |
| DELETE | `/transcripts/{id}` | Remove a stored transcript |

**POST `/transcripts/fetch` request:**

```json
{
  "ticker": "JPM",
  "quarter": "Q4-2025"  // optional, defaults to most recent
}
```

### 4.2 Analysis

| Method | Endpoint | Description |
|---|---|---|
| GET | `/analysis/{transcript_id}` | Full analysis for a transcript (sentiment, hedging, guidance, topics) |
| GET | `/analysis/{transcript_id}/sentiment` | Sentiment breakdown only |
| GET | `/analysis/{transcript_id}/hedging` | Hedging instances only |
| GET | `/analysis/{transcript_id}/guidance` | Forward-looking statements only |
| GET | `/analysis/{transcript_id}/topics` | Topic extraction only |
| POST | `/analysis/compare` | Compare two or more transcripts |

**POST `/analysis/compare` request:**

```json
{
  "transcript_ids": ["abc123", "def456"],
  "dimensions": ["sentiment", "hedging", "guidance", "topics"]  // optional, defaults to all
}
```

### 4.3 Search

| Method | Endpoint | Description |
|---|---|---|
| GET | `/search?company=JPM&topic=ai+investment` | Search across all transcripts by company, topic, speaker, or keyword |
| GET | `/search/quotes?query=credit+quality` | Find specific executive quotes matching a topic |

### 4.4 Company

| Method | Endpoint | Description |
|---|---|---|
| GET | `/companies` | List all companies with stored transcripts |
| GET | `/companies/{ticker}/timeline` | Sentiment and guidance trend across all stored quarters |

---

## 5. Data Model

### 5.1 Transcript

```python
class Transcript(BaseModel):
    id: str                        # UUID
    ticker: str                    # e.g., "JPM"
    company_name: str              # e.g., "JPMorgan Chase & Co."
    quarter: str                   # e.g., "Q4-2025"
    call_date: date
    source: str                    # "edgar" | "upload"
    source_url: Optional[str]
    raw_text: str
    sections: List[TranscriptSection]
    speakers: List[Speaker]
    created_at: datetime
    processed_at: Optional[datetime]
    status: str                    # "raw" | "processing" | "analyzed" | "error"
```

### 5.2 TranscriptSection

```python
class TranscriptSection(BaseModel):
    id: str
    transcript_id: str
    section_type: str              # "operator_intro" | "prepared_remarks" | "qa"
    speaker: Optional[Speaker]
    text: str
    order: int
    paragraphs: List[Paragraph]
```

### 5.3 Speaker

```python
class Speaker(BaseModel):
    name: str
    title: str                     # "CEO", "CFO", "Analyst at Goldman Sachs"
    role: str                      # "executive" | "analyst" | "operator"
    speaking_time_pct: Optional[float]
```

### 5.4 AnalysisResult

```python
class AnalysisResult(BaseModel):
    id: str
    transcript_id: str
    sentiment: SentimentResult
    hedging: HedgingResult
    guidance: List[GuidanceStatement]
    topics: List[TopicTag]
    comparison: Optional[ComparisonResult]  # populated when compared
    model_used: str                         # track which LLM version
    created_at: datetime
```

### 5.5 GuidanceStatement

```python
class GuidanceStatement(BaseModel):
    metric: str
    direction: str                 # "up" | "down" | "flat" | "range"
    magnitude: Optional[str]
    timeframe: str
    confidence_language: str
    conditions: List[str]
    source_text: str
    speaker: str
```

---

## 6. LLM Integration

### 6.1 Model

Claude (via Anthropic SDK). Use `claude-sonnet-4-6` for analysis tasks (cost-effective, fast enough for this use case). Reserve `claude-opus-4-6` only if extraction quality on complex transcripts proves insufficient.

### 6.2 Prompt Architecture

Each analysis dimension gets its own prompt template. This keeps prompts focused, outputs parseable, and makes it easy to iterate on one dimension without breaking others.

**Prompt files:**

```
prompts/
  upload_segmentation.py    # Parse raw text into structured sections (manual upload path only)
  upload_speaker_id.py      # Map names to roles (manual upload path only)
  sentiment_analysis.py     # Score tone across dimensions
  hedging_detection.py      # Flag qualifying/softening language
  guidance_extraction.py    # Pull forward-looking statements
  topic_tagging.py          # Classify topics against taxonomy
  quarter_comparison.py     # Compare two analyzed transcripts
```

Note: Section segmentation and speaker identification prompts are only needed for the manual upload path. When fetching via the EarningsCall API (Enhanced tier), speaker segments arrive pre-structured.

### 6.3 Prompt Design Principles

- **Structured output.** Every prompt requests JSON. Include the exact schema in the prompt.
- **Few-shot examples.** Include 2 to 3 examples of input/output pairs in each prompt, drawn from real (public) earnings transcripts.
- **Grounding instructions.** "Only flag hedging language that represents a change from prior quarter" prevents false positives.
- **Chunking strategy.** Transcripts can be 10,000+ words. Process by section, then aggregate. Don't try to fit an entire transcript in one call.

### 6.4 Cost Estimation

A typical earnings transcript is 8,000 to 12,000 words (~10,000 to 15,000 tokens input). Running all analysis prompts on a single transcript at Sonnet pricing (API fetch path, segmentation handled by EarningsCall):

- Sentiment (per section, ~4 sections): ~4 x 4K input + 1K output = ~20K total
- Hedging: ~15K input + 3K output
- Guidance: ~15K input + 3K output
- Topics: ~15K input + 1K output

**Rough total per transcript: ~70K tokens in, ~12K tokens out.**

For manual uploads, add ~15K input + 2K output for segmentation and ~15K input + 2K output for speaker identification.

At Sonnet rates, that's roughly $0.30 to $0.50 per transcript analysis (API path). Cheap enough to run liberally during development.

---

## 7. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Backend | Python, FastAPI | Beginner-friendly, auto-generated API docs at `/docs`, async support |
| Database | SQLite (V1), Postgres/Supabase (V2) | Start simple, migrate when you need concurrent writes |
| LLM | Claude API (Anthropic Python SDK) | Your existing toolchain, strong at structured extraction |
| Scheduling | APScheduler or cron | Fetch new transcripts after earnings season |
| Frontend | Next.js or React (deployed on Vercel) | Matches your existing Vercel workflow |
| Deployment (backend) | Railway or Render | Simple Python hosting, free tiers available |

---

## 8. Frontend Views

### 8.1 Home / Search

- Search bar: enter a ticker or company name
- Recent analyses displayed as cards
- Trending topics across all stored transcripts

### 8.2 Company Timeline

- Accessed via `/company/{ticker}`
- Visual timeline showing all analyzed quarters
- Sparkline charts for sentiment trend, hedging trend, guidance changes
- Click any quarter to drill into full analysis

### 8.3 Transcript Analysis View

- Accessed via `/analysis/{id}`
- Left panel: original transcript text with highlighted annotations (hedging = yellow, guidance = blue, sentiment shifts = red/green)
- Right panel: structured analysis output (tabbed: Sentiment | Hedging | Guidance | Topics)
- Executive summary card at the top

### 8.4 Comparison View

- Accessed via `/compare?ids={id1},{id2}`
- Side-by-side or unified diff view
- Key shifts highlighted with delta indicators
- Guidance comparison table (metric, Q(n-1) value, Q(n) value, change)

### 8.5 API Documentation

- Auto-generated Swagger UI at `/docs` (FastAPI gives this for free)
- This IS the demo. In an interview, you pull this up and walk through the architecture.

---

## 9. Non-Functional Requirements

### 9.1 Performance

- Transcript fetch and parse: < 5 seconds
- Full LLM analysis pipeline: < 60 seconds (acceptable for async processing; show a progress indicator)
- API response for pre-analyzed data: < 500ms
- Frontend page load: < 2 seconds

### 9.2 Error Handling

- EarningsCall API: handle rate limits, authentication errors, and missing transcripts gracefully
- LLM failures: retry with backoff, fall back gracefully (show partial results)
- Invalid transcripts (manual uploads): detect and surface parsing errors to the user
- Missing quarters: handle gracefully in comparison view

### 9.3 Security

- API key auth (simple bearer token) so you can demonstrate access control
- Environment variables for all secrets (Anthropic API key, EarningsCall API key, any DB credentials)
- No PII storage (transcripts are public data)

### 9.4 Observability

- Log every LLM call with: prompt template used, token count, latency, cost
- Track analysis accuracy over time (manual spot checks to start)

---

## 10. Build Phases

### Phase 1: Foundation (Get a Transcript On Screen)

1. FastAPI skeleton with the `/transcripts` router
2. Install `earningscall` Python SDK, wire up transcript fetching (start with AAPL, free tier)
3. Store pre-structured speaker segments from the API response
4. SQLite storage
5. Add manual upload path (plain text paste) with LLM-based section parsing
6. Simple frontend: search by ticker, display structured transcript with speaker labels
7. **Milestone:** You can type "AAPL" and see a structured, speaker-segmented transcript.

### Phase 2: Single-Transcript Analysis

1. Sentiment analysis prompt + endpoint
2. Hedging detection prompt + endpoint
3. Guidance extraction prompt + endpoint
4. Topic tagging prompt + endpoint
5. Combined `/analysis/{id}` endpoint
6. Frontend analysis view with highlighted annotations
7. **Milestone:** Full analysis output for any single transcript.

### Phase 3: The Killer Feature (Comparison)

1. Store multiple quarters per company
2. Quarter-over-quarter comparison prompt + endpoint
3. Comparison frontend view
4. Company timeline view with trend sparklines
5. **Milestone:** You can compare AAPL Q3 vs. Q4 and see what shifted.

### Phase 4: Polish for Demo Readiness

1. Search across all transcripts
2. API key auth
3. Loading states, error handling, empty states in the frontend
4. README with architecture diagram
5. Record a 2-minute walkthrough video
6. **Milestone:** You can demo this cold in an interview with no prep.

### Phase 5: Stretch Goals (V2)

- Integrate structured financial data (Alpha Vantage) to validate LLM-extracted numbers
- Upgrade to EarningsCall Enhanced tier for speaker-segmented data across all companies
- Batch processing: analyze all S&P 500 bank earnings in one run
- Alerts: notify when a tracked company files a new transcript
- Share analysis via public link (for sending to hiring managers as a signal)

---

## 11. Interview Demo Script

When demoing this project in a technical sales or solutions engineering interview, hit these beats:

1. **Open with the API docs** (`/docs`). "Let me show you the architecture first." Walk through endpoints.
2. **Fetch a live transcript.** Type a ticker, show the pipeline working.
3. **Show the analysis.** Highlight sentiment scoring, hedging flags, guidance extraction. Explain one prompt design decision.
4. **Run a comparison.** "Here's where it gets interesting." Show quarter-over-quarter shifts. Point to a specific hedging change and explain why an analyst would care.
5. **Talk about what you'd build next.** Alerts, batch processing, integration with portfolio management tools. Shows product sense.

The goal is to demonstrate that you can think about a problem end to end: data sourcing, AI integration, API design, and user experience, all grounded in a real domain.

---

## 12. Open Questions

- [ ] EarningsCall free tier limits: Confirm that AAPL and MSFT transcripts are sufficient for full pipeline development and testing before committing to a paid tier.
- [ ] Enhanced tier pricing: Determine cost for speaker-segmented data. If too expensive, fall back to Basic tier + LLM-based speaker parsing.
- [ ] Prompt evaluation: How do you measure whether the hedging detector is accurate? Manual review of 20 to 30 transcripts as a baseline.
- [ ] Transcript freshness: Test how quickly new earnings call transcripts appear in the EarningsCall API after the call happens.
- [ ] Shared backend with Regulatory Monitor: Build as a monorepo from the start, or standalone first and merge later?
- [ ] Cost at scale: At ~$0.40/transcript (LLM) + EarningsCall API fees, analyzing 100 companies x 4 quarters is roughly $160 to $200/year in LLM costs plus the API subscription. Acceptable for a portfolio project.
