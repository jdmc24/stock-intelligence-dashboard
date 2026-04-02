"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { TranscriptReader } from "@/components/transcript/TranscriptReader";
import { API_BASE, getTranscript, type Transcript } from "@/lib/api";

export default function TranscriptViewPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [t, setT] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const tr = await getTranscript(id);
        if (!cancelled) setT(tr);
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : "Failed";
          setError(
            msg === "Failed to fetch" || msg.includes("fetch")
              ? `${msg} — check API at ${API_BASE}`
              : msg,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <div className="page-canvas">
      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
              Transcript
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-3xl">
              {t ? (
                <>
                  {t.ticker}
                  {t.quarter ? <span className="text-zinc-500 dark:text-zinc-400"> · {t.quarter}</span> : null}
                </>
              ) : (
                "Transcript"
              )}
            </h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/analysis/${id}`} className="btn-primary px-3 py-2 text-sm">
              Analyze with Claude
            </Link>
            <Link href="/" className="btn-secondary px-3 py-2 text-sm">
              Home
            </Link>
          </div>
        </div>

        {error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        ) : !t ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
        ) : (
          <div className="space-y-4">
            <div className="surface-card p-4 text-sm">
              <div className="grid gap-2 text-zinc-600 dark:text-zinc-400">
                {t.company_name ? <div>Company: {t.company_name}</div> : null}
                <div>Status: {t.status}</div>
                {t.source_url ? (
                  <div className="truncate">
                    Source:{" "}
                    <a href={t.source_url} className="text-zinc-900 underline dark:text-zinc-100">
                      {t.source_url}
                    </a>
                  </div>
                ) : null}
              </div>
            </div>
            <TranscriptReader sections={t.sections} />
          </div>
        )}
      </main>
    </div>
  );
}
