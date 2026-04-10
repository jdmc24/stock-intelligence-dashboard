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
   | `SEC_USER_AGENT` | Required. e.g. `FSIntelligenceDashboard/1.0 (contact: you@example.com)` |
   | `API_BEARER_TOKEN` | Required. Long random string; **must match** `NEXT_PUBLIC_API_BEARER_TOKEN` on Vercel. |
   | `ANTHROPIC_API_KEY` | For regulatory enrichment (optional if you only use transcripts). |
   | `ANTHROPIC_MODEL` | Optional; default in code is `claude-sonnet-4-6`. |
   | `EARNINGSCALL_API_KEY` | Optional; needed for tickers beyond demo tier. |
   | `DATABASE_URL` | Default SQLite path is `./data/app.db` under `backend`. For persistence across deploys, add a **Volume** (see below). |
   | `REGULATORY_SCHEDULER_ENABLED` | Default `false`. Set `true` only if you want in-process ingest/enrich on an interval (uses API keys + cost). |

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

## 3. Checklist

- [ ] Railway: `API_BEARER_TOKEN` set  
- [ ] Vercel: `NEXT_PUBLIC_BACKEND_URL` + `NEXT_PUBLIC_API_BEARER_TOKEN` match Railway  
- [ ] Optional: volume + `DATABASE_URL` if you need durable SQLite  

### Railway build failed — quick checks

1. Open the failed deployment → **Build Logs** and read the **first error** (often `COPY failed`, `no such file`, `Railpack`, or `pip` / `apt` failures).
2. **Wrong Root Directory** — If you see Railpack trying to analyze the whole monorepo (frontend + backend), set Root Directory to `backend` *or* rely on the repo-root `Dockerfile` with Root Directory at repository root.
3. **Dockerfile not used** — Set **Config file path** to `/backend/railway.toml` or set **`RAILWAY_DOCKERFILE_PATH=Dockerfile`** on the service.
4. **Custom Start Command** — Remove overrides like `uvicorn ...` unless they match the container layout; a bad start command fails the **deploy** phase, not always the image build.
5. Paste the error snippet into an issue or chat if it still fails after the above.

## 4. Local `.env` unchanged

Developers still copy `.env.example` → `backend/.env` and `frontend/.env.local` for local runs; production uses only the host env vars above.
