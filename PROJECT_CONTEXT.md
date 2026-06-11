# Project Context — Stock Intelligence Dashboard

> Handoff doc for AI agents and contributors. Read this first; it points at the right files.

## Purpose

Full-stack public-equities research app: pull earnings call transcripts (EarningsCall), monitor Federal Register regulatory activity, and run LLM-backed analysis (Anthropic Claude). Monorepo: **Next.js** UI + **FastAPI** API, **SQLite** storage.

## Quick links

- **Live**: [stock-intelligence.io](https://stock-intelligence.io)
- **Repo**: [github.com/jdmc24/stock-intelligence-dashboard](https://github.com/jdmc24/stock-intelligence-dashboard)
- **Architecture diagram**: see `README.md` (`## Architecture`)
- **Deploy details**: `DEPLOYMENT.md`

## Status snapshot

- **Hosting**: API on **Railway**, UI on **Vercel**, custom domain wired on Vercel.
- **Working flows**:
  - Earnings: fetch transcript by ticker/quarter, run analysis with Claude.
  - Regulations: ingest Federal Register documents, enrich with Claude (with tool use + reflection — see below).
  - Compare / Search across stored content.
- **Auth**: simple shared **bearer token** (`API_BEARER_TOKEN` on Railway, mirrored as `NEXT_PUBLIC_API_BEARER_TOKEN` on Vercel).
- **DB**: SQLite via async SQLAlchemy. Production persistence requires a mounted volume on Railway with absolute `DATABASE_URL`.

## Agentic patterns implemented

The regulatory **enrichment** path is the agent-shaped flow. Three layers in increasing order of "agent-ness":

1. **Structured output** (always on) — Claude returns a JSON object matching `app/prompts/regulations_prompts.py` schema. Fields are post-normalized in `_norm_*` helpers in `regulations_enrichment.py`.
2. **Tool use** (`v2-tools` and later) — Claude has two read-only tools defined in `app/services/llm/regulatory_tools.py`:
   - `search_related_regulations(query, limit)` — keyword search over prior `reg_documents`.
   - `lookup_company_profile(ticker)` — fetch `company_reg_profiles` row.
   - The tool loop lives in `app/services/llm/anthropic_client.py` (`complete_json_with_tools_and_usage`). Each call is logged and persisted on `reg_enrichments.tool_calls_json`.
3. **Reflection pass** (`v3-reflection`) — after the main loop, one extra Claude call critiques the draft (see `_run_reflection` in `regulations_enrichment.py` and `REFLECTION_SYSTEM` in `regulations_prompts.py`). Only **severity + rationale** can be auto-corrected; structured tags are left as-is. The critique is appended to `tool_calls_json` as a synthetic `self_reflection` entry.

Frontend renders the full trace as a collapsible **"Agent reasoning"** panel on the regulation detail page (`frontend/src/components/regulations/AgentReasoningTrace.tsx`).

**Cost note**: a typical enriched doc = 2–5 Claude calls (1 main + 0–3 tool rounds + 1 reflection). To trim, gate reflection by initial severity.

## Where to look first

| What | File |
| --- | --- |
| Top-level architecture | `README.md` |
| Deploy instructions | `DEPLOYMENT.md` |
| FastAPI entrypoint | `backend/app/main.py` |
| Routers | `backend/app/routers/` |
| ORM models + schema migrations | `backend/app/models.py`, `backend/app/platform_init.py` |
| LLM client + tool loop | `backend/app/services/llm/anthropic_client.py` |
| Regulatory tools (TOOLS schema + dispatcher) | `backend/app/services/llm/regulatory_tools.py` |
| Regulatory enrichment orchestration | `backend/app/services/regulations_enrichment.py` |
| Versioned prompts | `backend/app/prompts/regulations_prompts.py` |
| UI agent trace panel | `frontend/src/components/regulations/AgentReasoningTrace.tsx` |
| Regulation detail page | `frontend/src/app/regulations/[id]/page.tsx` |
| Home UX (sticky nav, progress, toast) | `frontend/src/app/page.tsx`, `frontend/src/components/GettingStartedHome.tsx` |

## Recent direction (most-recent first)

- **`v3-reflection`**: second-pass critique + severity self-correction; `self_reflection` synthetic trace entry.
- **`v2-tools`**: tool use during enrichment, plus `RegEnrichment.tool_calls_json` column with SQLite-safe additive migration in `platform_init._ensure_additive_columns`.
- **UI**: collapsible Agent reasoning panel on reg detail page; special rendering for each known tool.
- **README**: `## Architecture` Mermaid diagram (no longer pretends to be a JSON-only LLM call).
- **Deploy**: custom domain `stock-intelligence.io` on Vercel; Railway service renamed `stock-intelligence`.
- **Home UX**: sticky in-page nav, fetch progress steps, toasts, a11y attributes, mobile touch targets.

## Open work (next session candidates)

- **Deploy agent suite**: local code is deploy-ready, but this sandbox is not a Git checkout, Vercel/Railway CLIs are not installed, and `gh auth status` reports an invalid token for `jdmc24`. Push/deploy from the real repo or re-auth/install deploy CLIs, then run `backend/scripts/smoke_agents.py` against Railway.
- **CI gate added**: `.github/workflows/ci.yml` runs no-cost backend agent routing/compile checks plus frontend lint/build. The existing `evals.yml` remains the paid Anthropic regulatory eval path.
- **Agent status endpoint**: `GET /api/agents/status` reports Claim Check, Earnings Drift, Product Discovery, and the unified smoke suite. `/research` renders the same agent-suite status.
- **Product Discovery Agent runtime check**: `/research` was verified locally in the in-app browser against FastAPI on `127.0.0.1:8001`; the page rendered status cards/latest brief with no console errors, and `backend/scripts/smoke_market_research.py` passed without `--trigger`.
- **Reflection cost**: gate by initial severity (only run reflection on `high`/`critical` drafts), or by document length.
- **Visual indication on detail page** when reflection actually changed severity (e.g. small badge "adjusted by reflection").
- **Multi-agent / specialized prompts**: more "theater" than substance for this app — only do if it's part of an interview narrative.
- **RAG / pgvector**: real lift, only worth it if "compare to similar prior regulations" becomes a real feature.
- **In-app alerts** when a `critical` enrichment matches a saved company profile.
- **CI**: minimal GitHub Action — `frontend` build + `backend` lint/test. Currently none.
- **Rate limiting**: bearer auth is fine; add per-IP/per-token throttling on `/transcripts/fetch` and analysis routes if traffic grows.
- **Observability**: structured logs + optional Sentry on both sides.

## Conventions

- Prefer **additive** schema migrations (see `_ensure_additive_columns`). Don't drop columns; add new ones, write null-safe code on the read side.
- Prompt changes get a **bumped `PROMPT_VERSION`** in `regulations_prompts.py` so we can analytics-slice by it later.
- Don't put secrets in the repo. `EARNINGSCALL_API_KEY`, `ANTHROPIC_API_KEY`, `API_BEARER_TOKEN` live in Railway. `NEXT_PUBLIC_*` mirrors live in Vercel.
- `LESSONS_LEARNED.md` is **gitignored** and intentionally local-only — don't commit it.

## How to continue (for an AI agent)

1. Open this file first, then `README.md`, then `git log --oneline -20`.
2. If you're going to edit code, run `npm run build` in `frontend/` and a Python import smoke test in `backend/` before committing.
3. Use the existing prompt-versioning + tool-calls trace pattern for any new agentic work — it pays dividends for debugging and demos.
4. Stay focused on **bounded, traceable** agent behavior. Avoid open-ended autonomy or speculative multi-agent setups unless they're explicitly on the open-work list above.
