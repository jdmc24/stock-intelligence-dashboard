"""Fixture-based eval runner for the regulatory enrichment agent.

Usage (from backend/ with a configured .venv):

    # Real Anthropic calls (default). Requires ANTHROPIC_API_KEY in env / .env.
    python -m app.evals.runner

    # Validate fixtures + scoring logic only (no API calls).
    python -m app.evals.runner --dry

    # Run only the first N fixtures.
    python -m app.evals.runner --limit 2

    # Run a single named fixture.
    python -m app.evals.runner --only capital_requirements_amendment

The runner spins up an isolated SQLite database in a temp directory so it
never touches your real app.db. It seeds two prior regulatory documents and
two company profiles so the tool-using agent has realistic data to call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _bootstrap_isolated_db() -> str:
    """Point app.settings at a fresh, throwaway SQLite file BEFORE any
    `app.*` import. Returns the temp DB path so we can clean it up later.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="eval_db_"))
    db_path = tmp_dir / "eval.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ.setdefault("SEC_USER_AGENT", "stock-intelligence-evals/0.1 (jake@example.com)")
    os.environ.setdefault("API_BEARER_TOKEN", "eval-runner-not-used")
    return str(db_path)


_TMP_DB = _bootstrap_isolated_db()

import datetime as dt  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    CompanyRegProfile,
    RegDocument,
    RegEnrichment,
)
from app.services.regulations_db import ensure_reg_search_fts  # noqa: E402
from app.settings import settings  # noqa: E402

from .scoring import score_fixture  # noqa: E402


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------- fixture loading ----------


def _load_seed() -> dict[str, Any]:
    with (FIXTURES_DIR / "_seed.json").open() as f:
        return json.load(f)


def _load_fixtures(only: str | None, limit: int | None) -> list[dict[str, Any]]:
    files = sorted(p for p in FIXTURES_DIR.glob("*.json") if not p.name.startswith("_"))
    if only:
        files = [p for p in files if p.stem == only]
        if not files:
            sys.exit(f"no fixture matches --only={only}")
    if limit is not None:
        files = files[:limit]
    fixtures: list[dict[str, Any]] = []
    for p in files:
        with p.open() as f:
            data = json.load(f)
        data["_file"] = p.name
        fixtures.append(data)
    return fixtures


# ---------- DB setup ----------


async def _init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_reg_search_fts(conn)


async def _seed_prior_state(seed: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        for prior in seed.get("prior_documents", []):
            doc = RegDocument(
                id=prior["id"],
                document_number=prior["document_number"],
                title=prior["title"],
                abstract=prior.get("abstract"),
                publication_date=dt.date.fromisoformat(prior["publication_date"]),
                document_type=prior["document_type"],
                agencies=json.dumps(prior.get("agencies", [])),
                federal_register_url=f"https://example.invalid/{prior['document_number']}",
                raw_text=prior["raw_text"],
                status="enriched",
            )
            session.add(doc)
            e = prior.get("enrichment") or {}
            if e:
                session.add(
                    RegEnrichment(
                        document_id=prior["id"],
                        summary=e.get("summary", ""),
                        change_type=e.get("change_type", "other"),
                        affected_products=json.dumps(e.get("affected_products", [])),
                        affected_functions=json.dumps(e.get("affected_functions", [])),
                        institution_types=json.dumps(e.get("institution_types", [])),
                        severity=e.get("severity", "medium"),
                        severity_rationale=e.get("severity_rationale"),
                        provisions=json.dumps([]),
                        model_used="seed",
                        prompt_version="seed",
                    )
                )
        for p in seed.get("company_profiles", []):
            session.add(
                CompanyRegProfile(
                    ticker=p["ticker"],
                    name=p["name"],
                    institution_types=json.dumps(p.get("institution_types", [])),
                    primary_products=json.dumps(p.get("primary_products", [])),
                    primary_functions=json.dumps(p.get("primary_functions", [])),
                    gics_sector=p.get("gics_sector"),
                    gics_sub_industry=p.get("gics_sub_industry"),
                )
            )
        await session.commit()


async def _insert_fixture_as_raw_doc(fixture: dict[str, Any]) -> str:
    """Insert the fixture as a `raw` RegDocument and return its id."""
    async with SessionLocal() as session:
        doc = RegDocument(
            document_number=fixture["document_number"],
            title=fixture["title"],
            abstract=fixture.get("abstract"),
            publication_date=dt.date.fromisoformat(fixture["publication_date"]),
            document_type=fixture["document_type"],
            agencies=json.dumps(fixture.get("agencies", [])),
            federal_register_url=f"https://example.invalid/{fixture['document_number']}",
            raw_text=fixture["raw_text"],
            status="raw",
        )
        session.add(doc)
        await session.commit()
        return doc.id


# ---------- enrichment readback ----------


async def _read_enrichment(doc_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """After enrich_document runs, read back the persisted enrichment row
    and reshape it to the dict shape used by the scoring functions.
    """
    async with SessionLocal() as session:
        res = await session.execute(
            select(RegEnrichment).where(RegEnrichment.document_id == doc_id)
        )
        row = res.scalar_one_or_none()
        if row is None:
            return {}, []
        enrichment = {
            "summary": row.summary,
            "change_type": row.change_type,
            "severity": row.severity,
            "severity_rationale": row.severity_rationale,
            "affected_products": json.loads(row.affected_products or "[]"),
            "affected_functions": json.loads(row.affected_functions or "[]"),
            "institution_types": json.loads(row.institution_types or "[]"),
        }
        tool_calls = json.loads(row.tool_calls_json or "[]")
        return enrichment, tool_calls


# ---------- printing ----------


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def _fmt(passed: bool) -> str:
    return f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"


def _print_fixture_result(
    fixture: dict[str, Any],
    enrichment: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    checks: list[tuple[str, bool, str]],
    error: str | None = None,
) -> tuple[int, int]:
    print(f"\n{'─' * 72}")
    print(f"{fixture['id']}  {DIM}({fixture['_file']}){RESET}")
    if error:
        print(f"  {RED}ENRICHMENT ERROR{RESET}: {error}")
        return (0, 1)
    tool_names = [tc.get("name") for tc in tool_calls]
    print(
        f"  {DIM}severity={enrichment.get('severity')}  "
        f"change_type={enrichment.get('change_type')}  "
        f"tools_called={tool_names or '(none)'}{RESET}"
    )
    passed = 0
    failed = 0
    for name, ok, msg in checks:
        prefix = _fmt(ok)
        print(f"  {prefix}  {name:<32}  {msg}")
        if ok:
            passed += 1
        else:
            failed += 1
    return (passed, failed)


def _print_summary(by_fixture: list[tuple[str, int, int]]) -> int:
    print(f"\n{'═' * 72}")
    print("SUMMARY")
    print(f"{'═' * 72}")
    total_pass = 0
    total_fail = 0
    for name, p, f in by_fixture:
        total_pass += p
        total_fail += f
        status = f"{GREEN}OK{RESET}" if f == 0 else f"{RED}{f} FAIL{RESET}"
        print(f"  {status:<20}  {name:<48}  {p} pass / {f} fail")
    print(f"{'─' * 72}")
    overall = f"{GREEN}ALL PASS{RESET}" if total_fail == 0 else f"{RED}{total_fail} FAIL{RESET}"
    print(f"  Overall: {overall}  ({total_pass} passing checks, {total_fail} failing)")
    return 0 if total_fail == 0 else 1


# ---------- main ----------


async def _run_async(args: argparse.Namespace) -> int:
    fixtures = _load_fixtures(only=args.only, limit=args.limit)
    if not fixtures:
        print("No fixtures to run.")
        return 0

    print(f"Eval DB: {_TMP_DB}")
    print(f"Fixtures: {len(fixtures)}")
    print(f"Mode: {'DRY (no API calls)' if args.dry else 'LIVE (calls Anthropic)'}")

    if args.dry:
        print(f"\n{YELLOW}Dry mode: validating fixtures + scoring imports, not running enrichment.{RESET}")
        for fx in fixtures:
            print(f"  - {fx['id']} ({fx['_file']}): {len(fx.get('expected', {}))} expectations")
        print("\nDry run OK.")
        return 0

    if not settings.anthropic_api_key:
        print(f"{RED}ANTHROPIC_API_KEY is not set. Add it to backend/.env or export it.{RESET}")
        return 2

    from app.services.regulations_enrichment import enrich_document

    await _init_db()
    await _seed_prior_state(_load_seed())

    by_fixture: list[tuple[str, int, int]] = []

    for fx in fixtures:
        doc_id = await _insert_fixture_as_raw_doc(fx)
        err: str | None = None
        try:
            async with SessionLocal() as session:
                await enrich_document(session, doc_id)
        except Exception as e:  # pragma: no cover — defensive: report, don't crash
            err = str(e)

        enrichment, tool_calls = await _read_enrichment(doc_id)
        if err:
            checks: list[tuple[str, bool, str]] = []
        else:
            checks = score_fixture(fx.get("expected", {}), enrichment, tool_calls)
        p, f = _print_fixture_result(fx, enrichment, tool_calls, checks, error=err)
        by_fixture.append((fx["id"], p, f))

    return _print_summary(by_fixture)


def main() -> None:
    parser = argparse.ArgumentParser(description="Regulatory enrichment eval harness")
    parser.add_argument("--dry", action="store_true", help="Validate fixtures + imports only; do not call the API")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N fixtures")
    parser.add_argument("--only", type=str, default=None, help="Run a single fixture by file stem (e.g. capital_requirements_amendment)")
    args = parser.parse_args()
    exit_code = asyncio.run(_run_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
