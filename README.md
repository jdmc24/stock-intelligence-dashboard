# Earnings Call Analyzer

Monorepo for a web app that fetches earnings call transcripts from SEC EDGAR, parses them into sections/speakers, stores them (SQLite), and runs LLM analysis (Claude) to extract sentiment, hedging, guidance, topics, and quarter-over-quarter changes.
Monorepo for a web app that fetches earnings call transcripts via the EarningsCall API/SDK, parses them into sections/speakers, stores them (SQLite), and runs LLM analysis (Claude) to extract sentiment, hedging, guidance, topics, and quarter-over-quarter changes.

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

