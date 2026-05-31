"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SeverityBadge } from "@/components/regulations/SeverityBadge";
import {
  getRegulatoryImpactBatch,
  listRegulatoryDocuments,
  listTranscripts,
  type RegDocumentListItem,
  type RegulatoryImpactResponse,
  type Transcript,
} from "@/lib/api";

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function sortRegulatoryHighlights(items: RegDocumentListItem[]) {
  return [...items].sort((a, b) => {
    const sa = (a.enrichment?.severity ?? "").toLowerCase();
    const sb = (b.enrichment?.severity ?? "").toLowerCase();
    const da = SEVERITY_ORDER[sa] ?? 99;
    const db = SEVERITY_ORDER[sb] ?? 99;
    if (da !== db) return da - db;
    return (b.publication_date || "").localeCompare(a.publication_date || "");
  });
}

export function RecentActivity() {
  const [recent, setRecent] = useState<Transcript[]>([]);
  const [regHighlights, setRegHighlights] = useState<RegDocumentListItem[]>([]);
  const [impactByTicker, setImpactByTicker] = useState<
    Record<string, RegulatoryImpactResponse | null | undefined>
  >({});

  useEffect(() => {
    listTranscripts().then(setRecent).catch(() => {});
    listRegulatoryDocuments({ per_page: 12 })
      .then((res) => setRegHighlights(sortRegulatoryHighlights(res.items).slice(0, 4)))
      .catch(() => setRegHighlights([]));
  }, []);

  useEffect(() => {
    const tickers = [...new Set(recent.slice(0, 4).map((x) => x.ticker.trim().toUpperCase()))];
    if (tickers.length === 0) return;
    let cancelled = false;
    (async () => {
      try {
        const batch = await getRegulatoryImpactBatch(tickers, 90);
        if (cancelled) return;
        setImpactByTicker((prev) => {
          const next = { ...prev };
          for (const tk of tickers) {
            next[tk] = batch.by_ticker[tk] ?? null;
          }
          return next;
        });
      } catch {
        if (!cancelled) {
          setImpactByTicker((prev) => {
            const next = { ...prev };
            tickers.forEach((tk) => {
              next[tk] = null;
            });
            return next;
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [recent]);

  return (
    <section className="mt-12 border-t border-zinc-200/80 pt-10 dark:border-zinc-800">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Recent activity</h2>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Drill into transcripts and rules — or fetch new earnings on the{" "}
            <Link href="/earnings" className="font-medium text-teal-600 hover:underline dark:text-teal-400">
              earnings tools
            </Link>{" "}
            page.
          </p>
        </div>
        <Link href="/earnings" className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">
          Earnings fetch &amp; analysis →
        </Link>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="surface-card p-4 sm:p-5">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Earnings</h3>
          <ul className="mt-3 space-y-2">
            {recent.length ? (
              recent.slice(0, 4).map((t) => {
                const tk = t.ticker.trim().toUpperCase();
                const impact = impactByTicker[tk];
                const top = impact?.matches?.[0];
                return (
                  <li key={t.id} className="rounded-lg border border-zinc-200/90 px-3 py-2 dark:border-zinc-800">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                      <span className="font-medium text-zinc-900 dark:text-zinc-100">
                        {t.ticker}
                        {t.quarter ? <span className="font-normal text-zinc-500"> · {t.quarter}</span> : null}
                      </span>
                      <div className="flex gap-2 text-xs">
                        <Link href={`/company/${encodeURIComponent(t.ticker)}`} className="text-teal-600 hover:underline dark:text-teal-400">
                          Company
                        </Link>
                        {t.status === "analyzed" ? (
                          <Link href={`/analysis/${t.id}`} className="text-teal-600 hover:underline dark:text-teal-400">
                            Analysis
                          </Link>
                        ) : (
                          <Link href={`/transcripts/${t.id}`} className="text-teal-600 hover:underline dark:text-teal-400">
                            Transcript
                          </Link>
                        )}
                      </div>
                    </div>
                    {top ? (
                      <p className="mt-1 line-clamp-1 text-xs text-zinc-500">
                        Reg match:{" "}
                        <Link href={`/regulations/${top.id}`} className="text-teal-700 hover:underline dark:text-teal-300">
                          {top.title}
                        </Link>
                      </p>
                    ) : null}
                  </li>
                );
              })
            ) : (
              <li className="text-sm text-zinc-600 dark:text-zinc-400">No transcripts yet.</li>
            )}
          </ul>
        </div>

        <div className="surface-card p-4 sm:p-5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Regulations</h3>
            <Link href="/regulations" className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">
              All
            </Link>
          </div>
          <ul className="mt-3 space-y-2">
            {regHighlights.length ? (
              regHighlights.map((doc) => (
                <li key={doc.id}>
                  <Link
                    href={`/regulations/${doc.id}`}
                    className="block rounded-lg border border-zinc-200/90 px-3 py-2 transition hover:border-teal-500/30 dark:border-zinc-800"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-zinc-500">{doc.publication_date}</span>
                      {doc.enrichment?.severity ? <SeverityBadge severity={doc.enrichment.severity} /> : null}
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-xs font-medium leading-snug text-zinc-900 dark:text-zinc-100">
                      {doc.title}
                    </p>
                  </Link>
                </li>
              ))
            ) : (
              <li className="text-sm text-zinc-600 dark:text-zinc-400">No documents loaded yet.</li>
            )}
          </ul>
        </div>
      </div>
    </section>
  );
}
