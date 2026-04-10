# Lessons Learned (Stock Intelligence Dashboard)

Working notes you can paste into a blog post later. Add bullets as they happen—don’t worry about polish.

## 1) Problem framing

- **What I was trying to build**:
- **Who it’s for**:
- **Success criteria**:

## 2) Architecture + key decisions

- **Why a monorepo (one repo for backend + frontend)**:
  - Keeps API contracts, shared env examples, and deploy docs in one place—one clone, one PR can touch both sides.
  - When building with coding agents, a single tree often means **less setup friction**: the assistant can see `backend/` and `frontend/` together without juggling two repos or cross-repo PRs. (You can still split repos later if team/process needs it.)
- **Monorepo split**: `backend/` (FastAPI) + `frontend/` (Next.js)
- **Data storage**: SQLite locally; persisted volume recommended in production
- **Auth model**: simple bearer token for API calls from the browser
- **Batching / performance choices**:

## 3) Deployment lessons (Railway + Vercel)

- **Goal: host the app in production (“in the cloud”)** — users hit HTTPS URLs; the API runs on a server, not on a developer laptop.
- **We did not want to depend on `uvicorn` locally** for every browser/API action. The browser should call the deployed API.
  - **Backend**: FastAPI on **Railway** (long-running `uvicorn` there).
  - **Frontend**: Next.js on **Vercel** with **`NEXT_PUBLIC_BACKEND_URL`** = Railway public URL and **`NEXT_PUBLIC_API_BEARER_TOKEN`** matching Railway **`API_BEARER_TOKEN`**.
  - **After changing `NEXT_PUBLIC_*`**: redeploy Vercel so the client bundle picks up the new values.
- **Confusing gotcha**: Vercel can show the correct `NEXT_PUBLIC_BACKEND_URL` in the dashboard, but you still see requests to **`http://127.0.0.1:8000`** when:
  - you’re running **`npm run dev` locally** and **`frontend/.env.local`** is missing or still points at localhost (Next defaults to `127.0.0.1:8000` if unset); or
  - you’re on an old **Preview** deployment built before env vars existed; or
  - env vars were added but that deployment wasn’t **redeployed**.
  - Rule of thumb: **which URL is in the address bar?** `localhost` → fix `.env.local` + restart dev server. `vercel.app` → fix/redeploy that Vercel environment.

- **Why Railway for backend + Vercel for frontend (instead of one platform)**:
  - Railway is a good fit for a long-running FastAPI service with a predictable HTTP port and optional background work.
  - Vercel is a good fit for Next.js (routing/SSR) and makes frontend deploys, previews, and rollbacks very easy.
  - Trying to force a “single provider” would either make the backend experience worse (shoehorning a long-running API into a frontend-first host) or make the frontend experience worse (losing Vercel’s Next.js-native workflow).
- **Monorepo gotchas**:
  - Root directory matters (Railway service root vs Vercel root directory).
  - Config-as-code paths can be non-obvious in monorepos.
- **Vercel ↔ GitHub**:
  - The **Vercel project** is tied to one Git repo; if you had a duplicate project (e.g. `…-vercel`) and later connect **`stock-intelligence-dashboard`**, check **Deployments** on the project that actually uses that connection—manual “Redeploy” only rebuilds what’s already linked; a **git push** to `main` triggers a fresh deployment once Git integration is correct.
  - GitHub App **repository access** must include the repo you want; otherwise it won’t appear in the connect picker until you adjust permissions.
- **Vercel Deploy Hooks** (optional, separate from Git webhooks):
  - A **deploy hook** is a secret URL (Settings → Git → Deploy Hooks) that triggers a **Production** build for a branch (e.g. `main`) when you `GET` or `POST` it—useful if push→deploy isn’t firing yet or you want CI/cron to trigger deploys.
  - Treat the URL like a password (revoke if leaked). Normal workflow is still **push to `main`** → automatic deployment via the GitHub integration; the hook is a backup / manual trigger, not a replacement for fixing integration.
- **Secrets / env vars**:
  - Railway required: `SEC_USER_AGENT`, `API_BEARER_TOKEN`
  - Vercel required: `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_API_BEARER_TOKEN`
  - Preview vs Production env scopes can cause “works locally, fails in cloud.”
  - Bearer-token mismatch can be deceptively time-consuming: tokens must match exactly, and `NEXT_PUBLIC_*` vars are baked into the build (so you must redeploy after changes).
- **Persistence**:
  - SQLite can reset on redeploy without a mounted volume + absolute `DATABASE_URL`.
- **Debug workflow that worked**:
  - Reproduce with `curl` to separate “backend auth” from “frontend env injection.”

## 4) Federal Register pipeline lessons

- **Ingest vs enrich**:
  - Ingest pulls raw FR docs.
  - Enrich adds summaries/severity/tags (requires Claude / `ANTHROPIC_API_KEY`).
- **Operational considerations**:
  - Cost controls, rate limits, retries, and when to run scheduled jobs.

## 5) What I’d improve next

- **Reliability**:
- **Observability** (logs, metrics, traces):
- **Security** (token rotation, least privilege, secrets hygiene):
- **UX** (empty states, progress, error messages):

## 6) “Receipts” (things I can show in interviews)

- **Deployed URLs** (redact secrets):
- **Before/after screenshots**:
- **Interesting bugs and how I debugged them**:
- **Trade-offs I made and why**:

