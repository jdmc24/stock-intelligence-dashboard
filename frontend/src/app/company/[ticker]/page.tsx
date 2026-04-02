"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { SeverityBadge } from "@/components/regulations/SeverityBadge";
import {
  type CompanyRegProfile,
  type CompanyTimeline,
  getCompanyRegProfile,
  getCompanyTimeline,
  getRegulatoryImpactByTicker,
  type RegulatoryImpactResponse,
} from "@/lib/api";

export default function CompanyDashboardPage() {
  const params = useParams();
  const ticker = typeof params.ticker === "string" ? params.ticker.trim().toUpperCase() : "";
  const [profile, setProfile] = useState<CompanyRegProfile | null>(null);
  const [timeline, setTimeline] = useState<CompanyTimeline | null>(null);
  const [impact, setImpact] = useState<RegulatoryImpactResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    (async () => {
      try {
        const p = await getCompanyRegProfile(ticker);
        if (cancelled) return;
        setProfile(p);

        const [tl, imp] = await Promise.all([
          getCompanyTimeline(ticker).catch((e: Error) => {
            if (e.message?.includes("404") || e.message?.includes("No transcripts")) return null;
            throw e;
          }),
          p ? getRegulatoryImpactByTicker(ticker, 90).catch(() => null) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setTimeline(tl);
        setImpact(imp);
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  if (!ticker) {
    return (
      <div className="page-canvas px-6 py-10">
        <p className="text-sm text-zinc-600">Invalid ticker.</p>
      </div>
    );
  }

  return (
    <div className="page-canvas">
      <main className="mx-auto max-w-5xl px-6 py-10">
        <Link href="/" className="text-sm font-medium text-teal-600 hover:underline dark:text-teal-400">
          ← Home
        </Link>

        <div className="mt-6">
          <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
            Company dashboard
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
            {profile?.name ?? ticker}
            <span className="ml-2 font-mono text-2xl text-zinc-500">{ticker}</span>
          </h1>
          {profile?.gics_sub_industry ? (
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{profile.gics_sub_industry}</p>
          ) : null}
        </div>

        {loadError ? (
          <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
            {loadError}
          </div>
        ) : null}

        {loading ? (
          <p className="mt-8 text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
        ) : (
          <div className="mt-8 grid gap-8 lg:grid-cols-2 lg:gap-10">
            <section className="surface-card p-5 sm:p-6">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Earnings &amp; analysis</h2>
                <Link href="/compare" className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">
                  Compare
                </Link>
              </div>
              {!timeline?.points?.length ? (
                <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
                  No analyzed transcripts for this ticker yet. Fetch a call on the home page, then run analysis.
                </p>
              ) : (
                <ul className="mt-4 space-y-3">
                  {timeline.points.map((pt) => (
                    <li key={pt.transcript_id}>
                      <Link
                        href={`/analysis/${pt.transcript_id}`}
                        className="block rounded-xl border border-zinc-200/90 p-3 transition hover:border-teal-500/30 hover:bg-teal-50/40 dark:border-zinc-800 dark:hover:border-teal-500/25 dark:hover:bg-zinc-900/50"
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <span className="font-medium text-zinc-900 dark:text-zinc-100">
                            {pt.quarter ?? "Call"}
                            {pt.call_date ? (
                              <span className="ml-2 font-normal text-zinc-500">
                                · {new Date(pt.call_date).toLocaleDateString()}
                              </span>
                            ) : null}
                          </span>
                          {pt.hedging_score != null ? (
                            <span className="text-xs text-zinc-500">Hedging {pt.hedging_score.toFixed(2)}</span>
                          ) : null}
                        </div>
                        {pt.overall_tone ? (
                          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">Tone: {pt.overall_tone}</p>
                        ) : null}
                        {pt.top_topics.length ? (
                          <p className="mt-1 text-xs text-zinc-500">{pt.top_topics.slice(0, 5).join(" · ")}</p>
                        ) : null}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section id="relevant-regulations" className="surface-card scroll-mt-24 p-5 sm:p-6">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Relevant regulations</h2>
                <Link href="/regulations" className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">
                  Browse all
                </Link>
              </div>
              {!profile ? (
                <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
                  No regulatory product/function profile for <span className="font-mono">{ticker}</span>. Seed{" "}
                  <code className="rounded bg-zinc-100 px-1 font-mono text-xs dark:bg-zinc-900">company_profiles</code>{" "}
                  on the API to enable matching.
                </p>
              ) : (
                <>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {profile.primary_products.slice(0, 8).map((x) => (
                      <span
                        key={x}
                        className="rounded-full bg-teal-500/12 px-2 py-0.5 text-[11px] text-teal-900 dark:text-teal-100"
                      >
                        {x}
                      </span>
                    ))}
                  </div>
                  {impact?.note ? (
                    <p className="mt-4 text-sm text-amber-800 dark:text-amber-200/90">{impact.note}</p>
                  ) : null}
                  {!impact?.matches?.length ? (
                    <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
                      {impact?.note
                        ? null
                        : "No overlapping enriched rules in the lookback window, or enrichment pipeline not run yet."}
                    </p>
                  ) : (
                    <ul className="mt-4 space-y-3">
                      {impact.matches.map((m) => (
                        <li key={m.id}>
                          <Link
                            href={`/regulations/${m.id}`}
                            className="block rounded-xl border border-zinc-200/90 p-3 transition hover:border-teal-500/30 dark:border-zinc-800 dark:hover:border-teal-500/25"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs text-zinc-500">{m.publication_date}</span>
                              {m.enrichment?.severity ? <SeverityBadge severity={m.enrichment.severity} /> : null}
                            </div>
                            <p className="mt-1 text-sm font-medium leading-snug text-zinc-900 dark:text-zinc-100">
                              {m.title}
                            </p>
                            {m.enrichment?.summary ? (
                              <p className="mt-1 line-clamp-2 text-xs text-zinc-600 dark:text-zinc-400">
                                {m.enrichment.summary}
                              </p>
                            ) : null}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </section>
          </div>
        )}

        <p className="mt-10 text-xs text-zinc-500 dark:text-zinc-500">
          Regulatory matches use static product/function tags and enriched Federal Register documents. Not legal advice.
        </p>
      </main>
    </div>
  );
}
