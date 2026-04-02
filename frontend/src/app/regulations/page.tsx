"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CompanyProfileAdmin } from "@/components/regulations/CompanyProfileAdmin";
import { SeverityBadge } from "@/components/regulations/SeverityBadge";
import {
  getRegulatoryStatus,
  listRegulatoryDocuments,
  triggerRegulatoryEnrich,
  triggerRegulatoryIngest,
  type RegDocumentListItem,
  type RegulatoryPipelineStatus,
} from "@/lib/api";

const DOC_TYPES = ["", "Notice", "Rule", "Proposed Rule", "Presidential Document"];

export default function RegulationsPage() {
  const [items, setItems] = useState<RegDocumentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const perPage = 15;
  const [search, setSearch] = useState("");
  const [agency, setAgency] = useState("");
  const [docType, setDocType] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pipeline, setPipeline] = useState<RegulatoryPipelineStatus | null>(null);
  const [busy, setBusy] = useState<"ingest" | "enrich" | null>(null);
  const [filterTick, setFilterTick] = useState(0);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await listRegulatoryDocuments({
        page,
        per_page: perPage,
        search: search.trim() || undefined,
        agency: agency.trim() || undefined,
        type: docType.trim() || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [page, search, agency, docType, filterTick]);

  useEffect(() => {
    load();
  }, [load]);

  function applyFilters() {
    setPage(1);
    setFilterTick((t) => t + 1);
  }

  const refreshPipeline = useCallback(() => {
    getRegulatoryStatus()
      .then(setPipeline)
      .catch(() => setPipeline(null));
  }, []);

  useEffect(() => {
    refreshPipeline();
  }, [refreshPipeline, items.length, page]);

  async function onIngest() {
    setBusy("ingest");
    setError(null);
    try {
      await triggerRegulatoryIngest(3);
      await load();
      refreshPipeline();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ingest failed");
    } finally {
      setBusy(null);
    }
  }

  async function onEnrich() {
    setBusy("enrich");
    setError(null);
    try {
      await triggerRegulatoryEnrich(5);
      await load();
      refreshPipeline();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Enrich failed");
    } finally {
      setBusy(null);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / perPage));

  return (
    <div className="page-canvas">
      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="max-w-2xl">
          <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
            Regulatory monitor
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
            Federal Register feed
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Ingested documents from the Federal Register API, enriched with Claude for summaries, severity, and product
            tags. Not legal advice.
          </p>
          {pipeline ? (
            <div className="mt-4 space-y-2 text-xs text-zinc-600 dark:text-zinc-400">
              <p className="flex flex-wrap gap-x-3 gap-y-1">
                <span>
                  <strong className="font-medium text-zinc-800 dark:text-zinc-200">{pipeline.reg_documents_count}</strong>{" "}
                  docs ·{" "}
                  <strong className="font-medium text-zinc-800 dark:text-zinc-200">{pipeline.enriched_count}</strong>{" "}
                  enriched ·{" "}
                  <strong className="font-medium text-zinc-800 dark:text-zinc-200">{pipeline.raw_pending_count}</strong>{" "}
                  raw ·{" "}
                  <strong className="font-medium text-zinc-800 dark:text-zinc-200">{pipeline.processing_count}</strong>{" "}
                  processing ·{" "}
                  <strong className="font-medium text-zinc-800 dark:text-zinc-200">{pipeline.error_count}</strong> errors
                </span>
                {pipeline.enrichment_coverage_percent != null ? (
                  <span className="text-zinc-500">Coverage {pipeline.enrichment_coverage_percent}%</span>
                ) : null}
              </p>
              <p className="flex flex-wrap gap-x-3 gap-y-1 text-zinc-500">
                {pipeline.last_document_ingested_at ? (
                  <span>Last ingest: {new Date(pipeline.last_document_ingested_at).toLocaleString()}</span>
                ) : null}
                {pipeline.last_enrichment_at ? (
                  <span>Last enrich: {new Date(pipeline.last_enrichment_at).toLocaleString()}</span>
                ) : null}
                <span>{pipeline.company_profiles_count} company profiles</span>
                <span>{pipeline.anthropic_configured ? "Claude API configured" : "Claude API not configured"}</span>
              </p>
              <p className="flex flex-wrap gap-2">
                <span
                  className={
                    pipeline.enrichment_pipeline_ok
                      ? "rounded-md bg-emerald-500/15 px-2 py-0.5 text-emerald-900 dark:text-emerald-200"
                      : "rounded-md bg-amber-500/15 px-2 py-0.5 text-amber-900 dark:text-amber-200"
                  }
                >
                  Enrichment pipeline: {pipeline.enrichment_pipeline_ok ? "clear" : "action needed"}
                </span>
                <span
                  className={
                    pipeline.ticker_matching_ready
                      ? "rounded-md bg-emerald-500/15 px-2 py-0.5 text-emerald-900 dark:text-emerald-200"
                      : "rounded-md bg-zinc-500/15 px-2 py-0.5 text-zinc-700 dark:text-zinc-300"
                  }
                >
                  Ticker matching: {pipeline.ticker_matching_ready ? "ready" : "not ready"}
                </span>
              </p>
              {pipeline.warnings.length > 0 ? (
                <ul className="list-inside list-disc rounded-lg border border-amber-200/80 bg-amber-50/80 py-2 pl-3 text-amber-950 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-100/95">
                  {pipeline.warnings.map((w) => (
                    <li key={w} className="leading-snug">
                      {w}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>

        <CompanyProfileAdmin onSaved={refreshPipeline} />

        <div className="surface-card mt-8 p-5 sm:p-6">
          <div className="grid gap-4 sm:grid-cols-12">
            <div className="sm:col-span-4">
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Search</label>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Keywords in title, text, or summary"
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              />
            </div>
            <div className="sm:col-span-3">
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Agency (contains)</label>
              <input
                value={agency}
                onChange={(e) => setAgency(e.target.value)}
                placeholder="e.g. CFPB"
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              />
            </div>
            <div className="sm:col-span-3">
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Document type</label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t || "any"} value={t}>
                    {t || "Any"}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-end sm:col-span-2">
              <button type="button" onClick={applyFilters} className="btn-primary w-full">
                Apply
              </button>
            </div>
          </div>
          <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-500">
            After changing filters, click Apply (resets to page 1). Use backend{" "}
            <code className="rounded bg-zinc-100 px-1 font-mono text-[11px] dark:bg-zinc-900">/docs</code> for full API
            control.
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onIngest}
            disabled={busy !== null}
            className="btn-secondary text-sm"
          >
            {busy === "ingest" ? "Ingesting…" : "Fetch FR (3 days)"}
          </button>
          <button
            type="button"
            onClick={onEnrich}
            disabled={busy !== null}
            className="btn-secondary text-sm"
          >
            {busy === "enrich" ? "Enriching…" : "Run AI enrich (5)"}
          </button>
        </div>

        {error ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        ) : null}

        <div className="mt-8 space-y-4">
          {loading ? (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
          ) : items.length === 0 ? (
            <div className="surface-card p-6 text-sm text-zinc-600 dark:text-zinc-400">
              No documents yet. Use <strong className="font-medium text-zinc-800 dark:text-zinc-200">Fetch FR</strong> in
              Swagger or the button above, then enrich.
            </div>
          ) : (
            items.map((d) => (
              <Link
                key={d.id}
                href={`/regulations/${d.id}`}
                className="surface-card block p-5 transition hover:border-teal-500/25 hover:shadow-md dark:hover:border-teal-500/20"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-zinc-100 px-2 py-0.5 font-mono text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                        {d.document_number}
                      </span>
                      <span className="text-xs text-zinc-500">{d.publication_date}</span>
                      <span className="rounded-md border border-zinc-200 px-2 py-0.5 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
                        {d.document_type}
                      </span>
                      {d.enrichment?.severity ? <SeverityBadge severity={d.enrichment.severity} /> : null}
                    </div>
                    <h2 className="mt-2 text-base font-semibold leading-snug text-zinc-900 dark:text-zinc-100">
                      {d.title}
                    </h2>
                    <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                      {d.enrichment?.summary ?? d.abstract ?? "No summary yet — run enrichment."}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {d.agencies.slice(0, 4).map((a) => (
                        <span
                          key={a}
                          className="rounded-full bg-teal-500/10 px-2 py-0.5 text-[11px] text-teal-800 dark:text-teal-200"
                        >
                          {a}
                        </span>
                      ))}
                    </div>
                  </div>
                  <span className="shrink-0 text-xs font-medium text-teal-600 dark:text-teal-400">View →</span>
                </div>
              </Link>
            ))
          )}
        </div>

        {totalPages > 1 ? (
          <div className="mt-8 flex items-center justify-center gap-4">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="btn-secondary disabled:opacity-40"
            >
              Previous
            </button>
            <span className="text-sm text-zinc-600 dark:text-zinc-400">
              Page {page} of {totalPages} ({total} total)
            </span>
            <button
              type="button"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => p + 1)}
              className="btn-secondary disabled:opacity-40"
            >
              Next
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}
