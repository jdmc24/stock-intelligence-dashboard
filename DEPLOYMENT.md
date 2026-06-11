# Deploy: Railway (API) + Vercel (UI)

The **backend** is a long‑running FastAPI app (SQLite, optional scheduler). The **frontend** is Next.js. Deploy the API on **Railway** and the static/SSR app on **Vercel**, then point the UI at the API with public env vars.

## 1. Railway — backend

1. Create a project at [railway.app](https://railway.app) and **New service** → **GitHub repo** → select `stock-intelligence-dashboard` (or your repo’s current name).
2. Open the service → **Settings** → **Root Directory**:
   - **Recommended:** `backend` (smaller build context; uses `backend/Dockerfile`).
   - **Also supported:** leave Root Directory empty or `/` (repository root). The repo now includes a root **`Dockerfile`** that copies `backend/` into the image, so deploys still work if Root Directory was never set.
3. **Build**
   - Leave **Start Command** empty (the image already runs `uvicorn` with `$PORT`).
   - **Config as code (monorepo):** Railway loads `railway.toml` from the **repository root** by default, not from your Root Directory. If builds use Railpack/Nixpacks instead of Docker, open **Settings** → set **Config file path** to **`/backend/railway.toml`** (see [Railway monorepo guide](https://docs.railway.com/guides/monorepo)). Alternatively set a service variable **`RAILWAY_DOCKERFILE_PATH`** to `Dockerfile` (path is relative to Root Directory).
   - The repo includes **`backend/railway.toml`** with `builder = "DOCKERFILE"` for when that file is picked up via the path above.
4. **Variables** — add (use strong values for production):

   | Variable | Notes |
   |----------|--------|
   | `SEC_USER_AGENT` | Required for **SEC EDGAR** and **Federal Register** HTTP fetches. Use a descriptive string with contact info (not a generic bot UA). FR serves CAPTCHA HTML (still `200 OK`) to unidentified clients — this value is sent as `User-Agent` on every `federalregister.gov` request. |
   | `API_BEARER_TOKEN` | Required. Long random string; **must match** `NEXT_PUBLIC_API_BEARER_TOKEN` on Vercel. |
   | `ANTHROPIC_API_KEY` | For regulatory enrichment (optional if you only use transcripts). |
   | `ANTHROPIC_MODEL` | Optional; default in code is `claude-sonnet-4-6`. |
   | `EARNINGSCALL_API_KEY` | Optional; needed for tickers beyond demo tier. |
   | `DATABASE_URL` | Default SQLite path is `./data/app.db` under `backend`. For persistence across deploys, add a **Volume** (see below). |
   | `REGULATORY_SCHEDULER_ENABLED` | Default `false`. Set `true` only if you want in-process ingest/enrich on an interval (uses API keys + cost). |
   | `MARKET_RESEARCH_SCHEDULER_ENABLED` | Default `false`. Set `true` to run the daily customer-discovery brief generator in-process. |
   | `MARKET_RESEARCH_SCHEDULER_RUN_ON_STARTUP` | Default `false`. Set `true` only when you want a brief generated immediately on deploy/startup. |
   | `MARKET_RESEARCH_RSS_URLS` | Optional comma-separated RSS feeds for permitted market/audience signals; Hacker News Algolia is used even when this is blank. |
   | `OPENAI_API_KEY` | Optional; enables LLM classification and synthesis for the market research crawler. Without it, heuristic classification is used. |
   | `OPENAI_MODEL` | Optional; model for market-research classification and briefs. |

5. **Networking** → **Generate Domain** (or attach a custom domain). Copy the public URL, e.g. `https://your-api.up.railway.app`.
6. Smoke test: `GET https://your-api.up.railway.app/healthz` → `{"ok":true}` with no auth.  
   `GET /docs` should load Swagger with title **Stock Intelligence Dashboard API**.

### SQLite persistence on Railway

The default DB path is on the container filesystem and **can reset** when the service redeploys. To keep data:

- Add a **Volume** in Railway mounted e.g. at `/data`, then set:
  - `DATABASE_URL=sqlite+aiosqlite:////data/app.db`  
  (four slashes after `sqlite+aiosqlite:` for an absolute path.)

## 2. Vercel — frontend

1. Import the same GitHub repo at [vercel.com](https://vercel.com) → **Add New** → **Project**.
2. **Root Directory** → **`frontend`** (important).
3. **Environment Variables** (Production — and Preview if you want):

   | Name | Value |
   |------|--------|
   | `NEXT_PUBLIC_BACKEND_URL` | Your Railway public API URL, e.g. `https://your-api.up.railway.app` (no trailing slash). |
   | `NEXT_PUBLIC_API_BEARER_TOKEN` | **Same** string as Railway `API_BEARER_TOKEN`. |

4. Deploy. Open the Vercel URL; the app will call the Railway API from the browser (CORS is open in the API).

5. **Custom domain (optional)** — In the project → **Settings** → **Domains**, add **`stock-intelligence.io`** (and/or **`www.stock-intelligence.io`**) and complete the DNS steps Vercel shows. Production traffic then uses your domain; the default `*.vercel.app` host can remain as a fallback.

## 3. Checklist

- [ ] Railway: `API_BEARER_TOKEN` set  
- [ ] Railway: `SEC_USER_AGENT` set to a descriptive value (required for Federal Register fetches, not only SEC)  
- [ ] Vercel: `NEXT_PUBLIC_BACKEND_URL` + `NEXT_PUBLIC_API_BEARER_TOKEN` match Railway  
- [ ] Optional: volume + `DATABASE_URL` if you need durable SQLite  
- [ ] If Claude's **Agent reasoning** trace flags CAPTCHA / access-denial text in the document body: open **Regulations** in the app → **Repair FR bodies** (or `POST /api/regulations/admin/refetch-compromised`), then **Run AI enrich** again on the raw queue.

### Agent rollout smoke tests

After Railway and Vercel finish deploying:

- Open `/ask` and run: `Claim check: is JPM unusually exposed to new banking capital rules?`
- Confirm the live trace includes **Regulations specialist**, **Earnings specialist**, and **Claim Check Agent**.
- Confirm the answer includes a visible verdict (`supported`, `mixed`, `weakly_supported`, `contradicted`, or `unverifiable`) plus citations or explicit evidence gaps.
- Open `/ask` and run: `How has MSFT AI narrative drifted over the last several earnings calls?`
- Confirm the live trace includes **Earnings specialist** and **Earnings Drift Agent**, and does not run the regulations specialist for this earnings-only question.
- Run a normal Ask prompt, e.g. `What recent SEC rules might affect how MSFT discusses AI?`, to verify the regular synthesizer path still works.
- Optional discovery-agent check: if `MARKET_RESEARCH_SCHEDULER_ENABLED=true`, call `POST /api/market-research/briefs/trigger?lookback_hours=24&max_items=40`, then `GET /api/market-research/briefs/latest`.
- Open `/research` and confirm the Product Discovery Agent status cards and latest brief render.
- Confirm `GET /api/agents/status` returns the three deploy-ready agents and `suite_smoke_script=backend/scripts/smoke_agents.py`.

CLI smoke tests for the deployed API:

```bash
cd backend
BACKEND_URL="https://your-api.up.railway.app" \
API_BEARER_TOKEN="same-token-used-by-vercel" \
python3 scripts/smoke_agents.py
```

To generate a fresh Product Discovery Agent brief as part of the suite:

```bash
BACKEND_URL="https://your-api.up.railway.app" \
API_BEARER_TOKEN="same-token-used-by-vercel" \
python3 scripts/smoke_agents.py --trigger-market-research
```

Individual checks remain available for debugging:

```bash
BACKEND_URL="https://your-api.up.railway.app" \
API_BEARER_TOKEN="same-token-used-by-vercel" \
python3 scripts/smoke_claim_check.py

BACKEND_URL="https://your-api.up.railway.app" \
API_BEARER_TOKEN="same-token-used-by-vercel" \
python3 scripts/smoke_earnings_drift.py

BACKEND_URL="https://your-api.up.railway.app" \
API_BEARER_TOKEN="same-token-used-by-vercel" \
python3 scripts/smoke_market_research.py --trigger
```

The scripts call `POST /api/ask/stream` and fail unless the SSE trace includes the expected specialist/final agents plus a valid verdict or drift direction.
The market-research smoke test checks `/api/market-research/status`; with `--trigger`, it also generates a brief and checks `/briefs/latest`.

### Railway build failed — quick checks

1. Open the failed deployment → **Build Logs** and read the **first error** (often `COPY failed`, `no such file`, `Railpack`, or `pip` / `apt` failures).
2. **Wrong Root Directory** — If you see Railpack trying to analyze the whole monorepo (frontend + backend), set Root Directory to `backend` *or* rely on the repo-root `Dockerfile` with Root Directory at repository root.
3. **Dockerfile not used** — Set **Config file path** to `/backend/railway.toml` or set **`RAILWAY_DOCKERFILE_PATH=Dockerfile`** on the service.
4. **Custom Start Command** — Remove overrides like `uvicorn ...` unless they match the container layout; a bad start command fails the **deploy** phase, not always the image build.
5. Paste the error snippet into an issue or chat if it still fails after the above.

## 4. Local `.env` unchanged

Developers still copy `.env.example` → `backend/.env` and `frontend/.env.local` for local runs; production uses only the host env vars above.

## 5. GitHub Actions — agent eval suite (optional but recommended)

The repo also includes a no-cost **ci** workflow for deploy readiness. It runs backend agent routing checks, Python compile checks, frontend lint, and frontend build on PRs/pushes touching `backend/` or `frontend/`. It does not require API secrets.

The repo includes a deterministic eval suite for the regulatory enrichment agent (see [`backend/app/evals/`](./backend/app/evals/) and [`.github/workflows/evals.yml`](./.github/workflows/evals.yml)). It runs on every PR that touches the agent path and on manual `workflow_dispatch` from the GitHub Actions UI.

To enable it on a fork or fresh clone:

1. GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
2. Add `ANTHROPIC_API_KEY` with the same value used in Railway. This is a separate store from Railway env vars; the two do not sync.
3. Trigger the first run manually: **Actions** tab → **evals** → **Run workflow** → branch `main`.

A successful run takes ~3 minutes and costs roughly $0.10 in Anthropic charges. The README badge updates on the next page load.

The workflow uses path filters so unrelated PRs (docs, frontend-only changes) do not trigger eval runs and incur cost. Filters cover the LLM client, enrichment service, prompts, models, fixtures, and the workflow file itself.
