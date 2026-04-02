"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { FormattedAnalysis } from "@/components/analysis/FormattedAnalysis";
import { API_BASE, getAnalysis, type Analysis } from "@/lib/api";

export default function AnalysisPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [data, setData] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    async function poll() {
      try {
        const a = await getAnalysis(id);
        if (cancelled) return;
        setData(a);
        if (a.status === "processing") {
          setTimeout(poll, 2000);
        }
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "Failed";
        const hint =
          msg === "Failed to fetch" || msg.includes("fetch")
            ? ` The app could not reach the API at ${API_BASE}. Start uvicorn on that port (backend terminal), or restart \`npm run dev\` after changing .env.local.`
            : "";
        setError(msg + hint);
      }
    }

    poll();
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
              AI output
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-3xl">
              Analysis
            </h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/compare?ids=${encodeURIComponent(id)}`} className="btn-secondary px-3 py-2 text-sm">
              Compare quarters
            </Link>
            <Link href="/" className="btn-secondary px-3 py-2 text-sm">
              Back
            </Link>
          </div>
        </div>

        {error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        ) : null}

        {!error && !data ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
        ) : !error && data?.status === "processing" ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Running Claude analysis (sentiment, hedging, guidance, topics). This can take up to a minute…
          </p>
        ) : !error && data?.status === "error" ? (
          <div className="rounded-xl border border-red-200 bg-white p-4 text-sm dark:border-red-900/50 dark:bg-zinc-950">
            {data.error_message ?? "Unknown error"}
          </div>
        ) : error ? null : data ? (
          <FormattedAnalysis data={data} />
        ) : null}
      </main>
    </div>
  );
}
