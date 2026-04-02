"""LLM enrichment for ingested Federal Register documents."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RegDocument, RegEnrichment
from app.prompts import regulations_prompts as rp
from app.services.llm.anthropic_client import complete_json_with_usage
from app.services.regulations_db import fts_replace_for_document
from app.settings import settings

logger = logging.getLogger(__name__)

MAX_BODY_CHARS = 120_000


def _truncate_body(text: str) -> str:
    t = text.strip()
    if len(t) <= MAX_BODY_CHARS:
        return t
    head = MAX_BODY_CHARS * 7 // 10
    tail = MAX_BODY_CHARS - head - 50
    return t[:head] + "\n\n[... middle truncated for model context ...]\n\n" + t[-tail:]


def _parse_iso_date(val: Any) -> dt.date | None:
    if val is None:
        return None
    if isinstance(val, str) and len(val) >= 10:
        try:
            return dt.date.fromisoformat(val[:10])
        except ValueError:
            return None
    return None


def _norm_list(val: Any, allowed: frozenset[str]) -> list[str]:
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for x in val:
        if isinstance(x, str) and x in allowed:
            out.append(x)
    return out


def _norm_institution(val: Any) -> list[str]:
    allowed = frozenset(
        {"commercial_bank", "credit_union", "mortgage_servicer", "broker_dealer", "fintech", "insurance", "other"}
    )
    return _norm_list(val, allowed)


def _norm_severity(val: Any) -> str:
    s = str(val or "").lower()
    if s in ("low", "medium", "high", "critical"):
        return s
    return "medium"


def _norm_change_type(val: Any) -> str:
    s = str(val or "other").lower()
    ok = frozenset(
        {"new_rule", "amendment", "proposed_rule", "guidance", "enforcement", "withdrawal", "other"}
    )
    return s if s in ok else "other"


def _norm_provisions(val: Any) -> list[dict[str, Any]]:
    if not isinstance(val, list):
        return []
    out: list[dict[str, Any]] = []
    for p in val[:12]:
        if not isinstance(p, dict):
            continue
        out.append(
            {
                "title": str(p.get("title") or "")[:500],
                "description": str(p.get("description") or "")[:2000],
                "cfr_reference": str(p.get("cfr_reference") or "")[:200] if p.get("cfr_reference") else None,
            }
        )
    return out[:7]


def build_user_prompt(doc: RegDocument) -> str:
    agencies = json.loads(doc.agencies or "[]")
    agencies_s = ", ".join(agencies) if isinstance(agencies, list) else str(agencies)
    body = _truncate_body(doc.raw_text or "")
    products = ", ".join(rp.CANONICAL_PRODUCTS)
    functions = ", ".join(rp.CANONICAL_FUNCTIONS)
    return f"""Analyze this Federal Register document and return one JSON object with exactly these keys:

- summary: string, 3-5 sentences, plain language for a compliance officer.
- change_type: one of: new_rule, amendment, proposed_rule, guidance, enforcement, withdrawal, other
- effective_date: YYYY-MM-DD or null
- comment_deadline: YYYY-MM-DD or null
- compliance_deadline: YYYY-MM-DD or null
- is_final: boolean or null
- amends_existing: boolean or null
- existing_rule_reference: string or null
- affected_products: JSON array of strings, each value MUST be one of: {products}
- affected_functions: JSON array of strings, each value MUST be one of: {functions}
- institution_types: JSON array — values from: commercial_bank, credit_union, mortgage_servicer, broker_dealer, fintech, insurance, other
- severity: one of low, medium, high, critical
- severity_rationale: short string
- provisions: array of 3-7 objects with keys title, description, cfr_reference (string or null)

Severity: critical = imminent/heavy burden; high = material change; medium = needs review; low = informational.

Document metadata:
Title: {doc.title}
Publication date: {doc.publication_date.isoformat()}
Type: {doc.document_type}
Agencies: {agencies_s}

Document text:
---
{body}
---
"""


def _call_llm_sync(system: str, user: str) -> tuple[dict[str, Any], int, int]:
    return complete_json_with_usage(system, user, max_tokens=8192)


async def enrich_document(session: AsyncSession, doc_id: str) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    doc = await session.get(RegDocument, doc_id)
    if doc is None:
        raise ValueError("document not found")

    doc.status = "processing"
    await session.commit()

    try:
        user_msg = build_user_prompt(doc)
        try:
            parsed, in_t, out_t = await asyncio.to_thread(_call_llm_sync, rp.SYSTEM, user_msg)
        except ValueError:
            parsed, in_t, out_t = await asyncio.to_thread(
                _call_llm_sync,
                rp.SYSTEM,
                user_msg + "\n\nReply with a single valid JSON object only. No markdown.",
            )
    except Exception as e:
        logger.exception("LLM enrichment failed for %s", doc_id)
        doc.status = "error"
        await session.commit()
        raise RuntimeError(str(e)) from e

    try:
        summary = str(parsed.get("summary") or "").strip() or "(no summary)"
        change_type = _norm_change_type(parsed.get("change_type"))
        eff = _parse_iso_date(parsed.get("effective_date"))
        cd = _parse_iso_date(parsed.get("comment_deadline"))
        comp = _parse_iso_date(parsed.get("compliance_deadline"))
        is_final = parsed.get("is_final")
        if not isinstance(is_final, bool):
            is_final = None

        products = _norm_list(parsed.get("affected_products"), frozenset(rp.CANONICAL_PRODUCTS))
        functions = _norm_list(parsed.get("affected_functions"), frozenset(rp.CANONICAL_FUNCTIONS))
        inst = _norm_institution(parsed.get("institution_types"))
        severity = _norm_severity(parsed.get("severity"))
        rationale = str(parsed.get("severity_rationale") or "")[:4000]
        provisions = _norm_provisions(parsed.get("provisions"))

        await session.execute(delete(RegEnrichment).where(RegEnrichment.document_id == doc.id))

        en = RegEnrichment(
            document_id=doc.id,
            summary=summary,
            change_type=change_type,
            effective_date=eff,
            comment_deadline=cd,
            compliance_deadline=comp,
            is_final=is_final,
            affected_products=json.dumps(products),
            affected_functions=json.dumps(functions),
            institution_types=json.dumps(inst),
            severity=severity,
            severity_rationale=rationale or None,
            provisions=json.dumps(provisions),
            action_items=None,
            model_used=settings.anthropic_model,
            prompt_version=rp.PROMPT_VERSION,
            processing_cost_tokens=in_t + out_t,
        )
        session.add(en)

        parts = [
            doc.title,
            doc.abstract or "",
            summary,
            " ".join(p.get("description") or "" for p in provisions if isinstance(p, dict)),
        ]
        search_blob = " ".join(x for x in parts if x).strip()
        doc.search_text = search_blob
        doc.status = "enriched"
        await session.flush()

        await fts_replace_for_document(session, doc.id, search_blob)
        await session.commit()

        return {
            "document_id": doc.id,
            "document_number": doc.document_number,
            "prompt_version": rp.PROMPT_VERSION,
            "model": settings.anthropic_model,
            "input_tokens": in_t,
            "output_tokens": out_t,
            "severity": severity,
        }
    except Exception:
        doc.status = "error"
        await session.commit()
        raise


async def enrich_pending_documents(session: AsyncSession, limit: int = 5) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    lim = max(1, min(limit, 25))
    res = await session.execute(
        select(RegDocument)
        .where(RegDocument.status == "raw")
        .order_by(RegDocument.publication_date.desc())
        .limit(lim)
    )
    docs = list(res.scalars().all())
    results: list[dict[str, Any]] = []
    for doc in docs:
        try:
            info = await enrich_document(session, doc.id)
            results.append({"ok": True, **info})
        except Exception as e:
            results.append({"ok": False, "document_id": doc.id, "document_number": doc.document_number, "error": str(e)})
    ok_n = sum(1 for r in results if r.get("ok"))
    return {"requested": len(docs), "succeeded": ok_n, "results": results}


async def reprocess_document(session: AsyncSession, doc_id: str) -> dict[str, Any]:
    doc = await session.get(RegDocument, doc_id)
    if doc is None:
        raise ValueError("document not found")
    await session.execute(delete(RegEnrichment).where(RegEnrichment.document_id == doc_id))
    await session.execute(text("DELETE FROM reg_search_fts WHERE document_id = :did"), {"did": doc_id})
    doc.search_text = None
    doc.status = "raw"
    await session.commit()
    return await enrich_document(session, doc_id)
