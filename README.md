# Stock Intelligence Dashboard

Monorepo for **Stock Intelligence Dashboard**: earnings call transcripts (EarningsCall API), Federal Register regulatory monitoring, company regulatory profiles, and LLM analysis (Claude) — stored in SQLite for local development.

## GitHub repository name

To use the slug **`stock-intelligence-dashboard`** on GitHub: open the repo → **Settings** → **General** → **Repository name**, enter `stock-intelligence-dashboard`, and rename. Update your local remote if needed: `git remote set-url origin https://github.com/<you>/stock-intelligence-dashboard.git` (or your SSH URL). Reconnect **Railway** / **Vercel** to the renamed repo if integrations break.

## Repo layout

- `backend/`: FastAPI API (Swagger at `/docs`)
- `frontend/`: Next.js UI

## Quickstart (local dev)

### 1) Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs`.

### 2) Frontend

```bash
cd frontend
npm install
cp ../.env.example .env.local
npm run dev
```

Open `http://localhost:3000`.

## Environment variables

See `.env.example`.

## Deploy (production)

**Railway** (FastAPI) + **Vercel** (Next.js): step-by-step variables, volumes, and URLs are in [`DEPLOYMENT.md`](./DEPLOYMENT.md).

