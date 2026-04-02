"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { SeverityBadge } from "@/components/regulations/SeverityBadge";
import { getRegulatoryDocument, type RegDocumentDetail } from "@/lib/api";

export default function RegulationDetailPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [doc, setDoc] = useState<RegDocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setError(null);
    getRegulatoryDocument(id)
      .then((d) => {
        if (!cancelled) setDoc(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <div className="page-canvas">
        <main className="mx-auto max-w-5xl px-6 py-10">
          <Link href="/regulations" className="text-sm font-medium text-teal-600 hover:underline dark:text-teal-400">
            ← Regulations
          </Link>
          <p className="mt-6 text-sm text-red-700 dark:text-red-300">{error}</p>
        </main>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="page-canvas">
        <main className="mx-auto max-w-5xl px-6 py-10">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
        </main>
      </div>
    );
  }

  const full = doc.enrichment_full;
  const hasEnrichment = !!full || !!doc.enrichment;

  return (
    <div className="page-canvas">
      <main className="mx-auto max-w-5xl px-6 py-10">
        <Link href="/regulations" className="text-sm font-medium text-teal-600 hover:underline dark:text-teal-400">
          ← Regulations
        </Link>

        <div className="mt-6 max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-zinc-100 px-2 py-0.5 font-mono text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
              {doc.document_number}
            </span>
            <span className="text-xs text-zinc-500">{doc.publication_date}</span>
            <span className="rounded-md border border-zinc-200 px-2 py-0.5 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
              {doc.document_type}
            </span>
            <span className="rounded-md border border-zinc-200 px-2 py-0.5 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
              {doc.status}
            </span>
            {(full?.severity || doc.enrichment?.severity) ? (
              <SeverityBadge severity={full?.severity ?? doc.enrichment?.severity} />
            ) : null}
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-3xl">
            {doc.title}
          </h1>
          <div className="mt-4 flex flex-wrap gap-3">
            <a
              href={doc.federal_register_url}
              target="_blank"
              rel="noreferrer"
              className="btn-primary inline-flex text-sm"
            >
              Open on Federal Register
            </a>
            {doc.pdf_url ? (
              <a
                href={doc.pdf_url}
                target="_blank"
                rel="noreferrer"
                className="btn-secondary inline-flex text-sm"
              >
                PDF
              </a>
            ) : null}
          </div>
        </div>

        {!hasEnrichment ? (
          <div className="surface-card mt-8 p-5 text-sm text-zinc-600 dark:text-zinc-400">
            No AI enrichment yet. On the list page, use <strong className="text-zinc-800 dark:text-zinc-200">Run AI enrich</strong>{" "}
            or call <code className="font-mono text-xs">POST /api/regulations/enrich/trigger</code>.
          </div>
        ) : null}

        {full?.summary || doc.enrichment?.summary ? (
          <section className="surface-card mt-8 p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Summary</h2>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
              {full?.summary ?? doc.enrichment?.summary}
            </p>
            {full?.severity_rationale ? (
              <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Severity note: </span>
                {full.severity_rationale}
              </p>
            ) : null}
          </section>
        ) : null}

        {full ? (
          <section className="surface-card mt-6 p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Classification</h2>
            <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs text-zinc-500">Change type</dt>
                <dd className="font-medium text-zinc-800 dark:text-zinc-200">{full.change_type}</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-500">Model</dt>
                <dd className="font-mono text-xs text-zinc-700 dark:text-zinc-300">
                  {full.model_used} · {full.prompt_version}
                </dd>
              </div>
              {full.effective_date ? (
                <div>
                  <dt className="text-xs text-zinc-500">Effective</dt>
                  <dd>{full.effective_date}</dd>
                </div>
              ) : null}
              {full.comment_deadline ? (
                <div>
                  <dt className="text-xs text-zinc-500">Comment deadline</dt>
                  <dd>{full.comment_deadline}</dd>
                </div>
              ) : null}
              {full.compliance_deadline ? (
                <div>
                  <dt className="text-xs text-zinc-500">Compliance deadline</dt>
                  <dd>{full.compliance_deadline}</dd>
                </div>
              ) : null}
            </dl>
          </section>
        ) : null}

        {(full?.affected_products?.length || full?.affected_functions?.length || doc.enrichment) ? (
          <section className="surface-card mt-6 p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Impact tags</h2>
            <div className="mt-3">
              <p className="text-xs font-medium text-zinc-500">Products</p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {(full?.affected_products ?? doc.enrichment?.affected_products ?? []).map((t) => (
                  <span
                    key={t}
                    className="rounded-full bg-teal-500/15 px-2.5 py-0.5 text-xs text-teal-900 dark:text-teal-100"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
            <div className="mt-4">
              <p className="text-xs font-medium text-zinc-500">Functions</p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {(full?.affected_functions ?? doc.enrichment?.affected_functions ?? []).map((t) => (
                  <span
                    key={t}
                    className="rounded-full bg-emerald-500/15 px-2.5 py-0.5 text-xs text-emerald-900 dark:text-emerald-100"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
            {full?.institution_types?.length ? (
              <div className="mt-4">
                <p className="text-xs font-medium text-zinc-500">Institution types</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {full.institution_types.map((t) => (
                    <span
                      key={t}
                      className="rounded-full bg-zinc-500/15 px-2.5 py-0.5 text-xs text-zinc-800 dark:text-zinc-200"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {full?.provisions && full.provisions.length > 0 ? (
          <section className="surface-card mt-6 p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Key provisions</h2>
            <ul className="mt-4 space-y-4">
              {full.provisions.map((p, i) => (
                <li key={i} className="border-b border-zinc-200 pb-4 last:border-0 dark:border-zinc-800">
                  <p className="font-medium text-zinc-900 dark:text-zinc-100">{p.title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{p.description}</p>
                  {p.cfr_reference ? (
                    <p className="mt-1 font-mono text-xs text-zinc-500">{p.cfr_reference}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="mt-8">
          <button
            type="button"
            onClick={() => setShowRaw((s) => !s)}
            className="text-sm font-medium text-teal-700 hover:underline dark:text-teal-400"
          >
            {showRaw ? "Hide" : "Show"} full document text
          </button>
          {showRaw ? (
            <div className="surface-card mt-3 max-h-[min(70vh,600px)] overflow-y-auto p-4">
              <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-zinc-700 dark:text-zinc-300">
                {doc.raw_text}
              </pre>
            </div>
          ) : null}
        </section>

        <p className="mt-10 text-xs text-zinc-500 dark:text-zinc-500">
          Summaries and tags are AI-generated for informational purposes only, not legal or compliance advice.
        </p>
      </main>
    </div>
  );
}
