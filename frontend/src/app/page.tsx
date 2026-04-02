"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { SeverityBadge } from "@/components/regulations/SeverityBadge";
import { TranscriptReader } from "@/components/transcript/TranscriptReader";
import {
  API_BASE,
  fetchTranscript,
  getRegulatoryImpactBatch,
  getTranscript,
  listRegulatoryDocuments,
  listTranscripts,
  type RegDocumentListItem,
  type RegulatoryImpactResponse,
  Transcript,
  uploadTranscript,
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

export default function Home() {
  const [ticker, setTicker] = useState("AAPL");
  const now = useMemo(() => new Date(), []);
  const [selectedYear, setSelectedYear] = useState<number>(now.getFullYear());
  const [selectedQuarter, setSelectedQuarter] = useState<"recent" | "1" | "2" | "3" | "4">("recent");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [transcriptId, setTranscriptId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [recent, setRecent] = useState<Transcript[]>([]);
  const [regHighlights, setRegHighlights] = useState<RegDocumentListItem[]>([]);
  /** Per-ticker impact from `/api/regulations/impact/by-ticker` — `undefined` until loaded, `null` if no company profile (404). */
  const [impactByTicker, setImpactByTicker] = useState<
    Record<string, RegulatoryImpactResponse | null | undefined>
  >({});

  const title = useMemo(() => {
    if (!transcript) return "Earnings Call Analyzer";
    return `${transcript.ticker}${transcript.quarter ? ` · ${transcript.quarter}` : ""}`;
  }, [transcript]);

  const quarterLabel = useMemo(() => {
    if (selectedQuarter === "recent") return undefined;
    return `Q${selectedQuarter}-${selectedYear}`;
  }, [selectedQuarter, selectedYear]);

  const yearOptions = useMemo(() => {
    const y = now.getFullYear();
    const out: number[] = [];
    for (let i = 0; i < 8; i++) out.push(y - i);
    return out;
  }, [now]);

  useEffect(() => {
    listTranscripts().then(setRecent).catch(() => {});
  }, []);

  useEffect(() => {
    listRegulatoryDocuments({ per_page: 24 })
      .then((res) => setRegHighlights(sortRegulatoryHighlights(res.items).slice(0, 5)))
      .catch(() => setRegHighlights([]));
  }, []);

  useEffect(() => {
    const tickers = [...new Set(recent.slice(0, 5).map((x) => x.ticker.trim().toUpperCase()))];
    if (tickers.length === 0) return;
    let cancelled = false;
    setImpactByTicker((prev) => {
      const next = { ...prev };
      tickers.forEach((tk) => {
        next[tk] = undefined;
      });
      return next;
    });
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
        if (cancelled) return;
        setImpactByTicker((prev) => {
          const next = { ...prev };
          tickers.forEach((tk) => {
            next[tk] = null;
          });
          return next;
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [recent]);

  useEffect(() => {
    if (!transcriptId) return;
    let cancelled = false;

    async function poll() {
      const id = transcriptId;
      if (!id) return;
      try {
        const t = await getTranscript(id);
        if (cancelled) return;
        setTranscript(t);
        if (t.status === "processing") {
          setTimeout(poll, 1500);
        } else {
          listTranscripts().then(setRecent).catch(() => {});
          setBusy(false);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load transcript");
        setBusy(false);
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [transcriptId]);

  async function onFetch() {
    setError(null);
    setBusy(true);
    setTranscript(null);
    try {
      const res = await fetchTranscript(ticker.trim().toUpperCase(), quarterLabel);
      setTranscriptId(res.transcript_id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Fetch failed";
      const hint =
        msg.includes("fetch") || msg.includes("Failed")
          ? ` Cannot reach API at ${API_BASE}. Is uvicorn running on that port? Restart \`npm run dev\` after editing .env.local.`
          : "";
      setError(msg + hint);
      setBusy(false);
    }
  }

  async function onLoadSample() {
    setError(null);
    setBusy(true);
    setTranscript(null);
    try {
      const sample = `Operator:\nGood morning, and welcome to the Company Quarterly Earnings Conference Call.\n\nJamie Dimon:\nThanks, operator. We delivered strong results this quarter, driven by resilient consumer activity and disciplined expense management.\n\nJeremy Barnum:\nNet interest income reflected seasonal deposit trends and higher balances, while we continued to invest in technology and controls.\n\nQuestion-and-Answer Session\n\nAnalyst:\nCan you comment on credit quality and any early signs of stress?\n\nJamie Dimon:\nWe remain comfortable with our credit performance, though we’re watching pockets of weakness and will stay cautious if conditions change.`;

      const res = await uploadTranscript({
        ticker: ticker.trim().toUpperCase() || "JPM",
        quarter: quarterLabel ?? "Sample",
        raw_text: sample,
      });
      setTranscriptId(res.transcript_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setBusy(false);
    }
  }

  return (
    <div className="page-canvas relative overflow-hidden">
      <div
        className="pointer-events-none absolute inset-x-0 -top-24 h-72 bg-gradient-to-b from-teal-500/15 via-transparent to-transparent dark:from-teal-400/10"
        aria-hidden
      />
      <main className="relative mx-auto max-w-5xl px-6 py-10">
        <div className="flex max-w-2xl flex-col gap-2">
          <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
            Earnings &amp; regulatory intelligence
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
            {title}
          </h1>
          <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Fetch earnings transcripts, run AI analysis, and track Federal Register items that overlap your company
            profiles—on one platform.
          </p>
        </div>

        <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <section className="surface-card flex flex-col p-5 sm:p-6">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Recent earnings</h2>
              <Link
                href="/compare"
                className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400"
              >
                Compare
              </Link>
            </div>
            <ul className="mt-3 flex-1 space-y-2">
              {recent.length ? (
                recent.slice(0, 5).map((t) => {
                  const tk = t.ticker.trim().toUpperCase();
                  const impact = impactByTicker[tk];
                  const top = impact?.matches?.[0];
                  return (
                    <li key={t.id}>
                      <div className="rounded-xl border border-zinc-200/90 px-3 py-2 dark:border-zinc-800">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="min-w-0 text-sm">
                            <span className="font-medium text-zinc-900 dark:text-zinc-100">{t.ticker}</span>
                            {t.quarter ? (
                              <span className="text-zinc-500 dark:text-zinc-400"> · {t.quarter}</span>
                            ) : null}
                            <span className="ml-2 text-xs text-zinc-500">{t.status}</span>
                          </div>
                          <div className="flex flex-wrap gap-2 text-xs">
                            <Link
                              href={`/company/${encodeURIComponent(t.ticker)}#relevant-regulations`}
                              className="font-medium text-teal-600 hover:underline dark:text-teal-400"
                            >
                              Relevant regs
                            </Link>
                            <Link
                              href={`/company/${encodeURIComponent(t.ticker)}`}
                              className="font-medium text-teal-600 hover:underline dark:text-teal-400"
                            >
                              Company
                            </Link>
                            <Link
                              href={`/transcripts/${t.id}`}
                              className="font-medium text-teal-600 hover:underline dark:text-teal-400"
                            >
                              Transcript
                            </Link>
                            {t.status === "analyzed" ? (
                              <Link
                                href={`/analysis/${t.id}`}
                                className="font-medium text-teal-600 hover:underline dark:text-teal-400"
                              >
                                Analysis
                              </Link>
                            ) : null}
                          </div>
                        </div>
                        {impact === undefined ? (
                          <p className="mt-1.5 text-[11px] text-zinc-400">Loading regulatory match…</p>
                        ) : impact === null ? (
                          <p className="mt-1.5 text-[11px] text-zinc-500">
                            No regulatory profile for <span className="font-mono">{tk}</span> — add one in the API to
                            link Federal Register items.
                          </p>
                        ) : top ? (
                          <div className="mt-1.5 border-t border-zinc-200/80 pt-1.5 dark:border-zinc-800">
                            <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                              Latest relevant rule
                            </p>
                            <Link
                              href={`/regulations/${top.id}`}
                              className="mt-0.5 line-clamp-2 text-xs leading-snug text-teal-700 hover:underline dark:text-teal-300"
                            >
                              <span className="text-zinc-500">{top.publication_date} · </span>
                              {top.title}
                            </Link>
                          </div>
                        ) : (
                          <p className="mt-1.5 text-[11px] text-zinc-500">
                            {impact?.note ?? "No overlapping enriched rules in the last 90 days."}{" "}
                            <Link
                              href={`/company/${encodeURIComponent(t.ticker)}#relevant-regulations`}
                              className="text-teal-600 hover:underline dark:text-teal-400"
                            >
                              Details
                            </Link>
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })
              ) : (
                <li className="text-sm text-zinc-600 dark:text-zinc-400">No transcripts yet. Fetch one below.</li>
              )}
            </ul>
          </section>

          <section className="surface-card flex flex-col p-5 sm:p-6">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Regulatory highlights</h2>
              <Link href="/regulations" className="text-xs font-medium text-teal-600 hover:underline dark:text-teal-400">
                All regulations
              </Link>
            </div>
            <ul className="mt-3 flex-1 space-y-2">
              {regHighlights.length ? (
                regHighlights.map((doc) => (
                  <li key={doc.id}>
                    <Link
                      href={`/regulations/${doc.id}`}
                      className="block rounded-xl border border-zinc-200/90 px-3 py-2 transition hover:border-teal-500/30 hover:bg-teal-50/40 dark:border-zinc-800 dark:hover:border-teal-500/25 dark:hover:bg-zinc-900/50"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-zinc-500">{doc.publication_date}</span>
                        {doc.enrichment?.severity ? (
                          <SeverityBadge severity={doc.enrichment.severity} />
                        ) : null}
                      </div>
                      <p className="mt-0.5 line-clamp-2 text-sm font-medium leading-snug text-zinc-900 dark:text-zinc-100">
                        {doc.title}
                      </p>
                    </Link>
                  </li>
                ))
              ) : (
                <li className="text-sm text-zinc-600 dark:text-zinc-400">
                  No documents loaded. Open Regulations to ingest from the Federal Register.
                </li>
              )}
            </ul>
          </section>
        </div>

        <div className="surface-card mt-8 grid grid-cols-1 gap-4 p-5 sm:grid-cols-12 sm:p-6">
          <div className="sm:col-span-3">
            <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Ticker</label>
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              placeholder="AAPL"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setTicker("AAPL")}
                className="rounded-lg border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-black dark:text-zinc-200 dark:hover:bg-zinc-900/40"
              >
                AAPL
              </button>
              <button
                type="button"
                onClick={() => setTicker("MSFT")}
                className="rounded-lg border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-black dark:text-zinc-200 dark:hover:bg-zinc-900/40"
              >
                MSFT
              </button>
            </div>
          </div>
          <div className="sm:col-span-4">
            <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Quarter</label>
            <div className="mt-1 grid grid-cols-2 gap-2">
              <select
                value={selectedQuarter}
                onChange={(e) => setSelectedQuarter(e.target.value as typeof selectedQuarter)}
                className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              >
                <option value="recent">Most recent</option>
                <option value="1">Q1</option>
                <option value="2">Q2</option>
                <option value="3">Q3</option>
                <option value="4">Q4</option>
              </select>
              <select
                value={selectedYear}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                disabled={selectedQuarter === "recent"}
                className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900/80"
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
            <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              Sending: <span className="font-mono">{quarterLabel ?? "recent"}</span>
            </div>
          </div>
          <div className="flex items-end sm:col-span-5">
            <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={onFetch}
                disabled={busy || ticker.trim().length === 0}
                className="btn-primary w-full"
              >
                {busy ? "Working…" : "Fetch from EarningsCall"}
              </button>
              <button
                type="button"
                onClick={onLoadSample}
                disabled={busy}
                className="btn-secondary w-full"
              >
                Load sample transcript
              </button>
            </div>
          </div>
          {error ? (
            <div className="sm:col-span-12 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
              {error}
            </div>
          ) : null}
          {transcriptId ? (
            <div className="flex flex-col gap-2 sm:col-span-12 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-zinc-500 dark:text-zinc-400">
                {transcript?.status ? <>Status: {transcript.status}</> : null}
              </div>
              {transcript && transcript.status !== "processing" && transcript.status !== "error" ? (
                <Link href={`/analysis/${transcriptId}`} className="btn-primary inline-flex w-fit items-center justify-center">
                  Analyze with Claude
                </Link>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-12">
          <section className="lg:col-span-8">
            {transcript?.sections?.length ? (
              <TranscriptReader sections={transcript.sections} />
            ) : transcript?.status === "processing" ? (
                <div className="surface-card p-4 text-sm text-zinc-600 dark:text-zinc-400">
                  Working… this will auto-refresh.
                </div>
              ) : transcript?.status === "error" ? (
                <div className="surface-card border-red-200/90 p-4 text-sm text-red-700 dark:border-red-900/50 dark:text-red-200">
                  {transcript.error_message ?? "Unknown error"}
                </div>
              ) : (
                <div className="surface-card p-4 text-sm text-zinc-600 dark:text-zinc-400">
                  No transcript loaded yet. Fetch AAPL to start.
                </div>
              )}
          </section>

          <aside className="lg:col-span-4">
            <h2 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">Recent transcripts</h2>
            <div className="mt-3 space-y-2">
              {recent.length ? (
                recent.slice(0, 12).map((t) => (
                  <div
                    key={t.id}
                    className="w-full rounded-2xl border border-zinc-200/90 bg-white/90 p-3 text-left text-sm shadow-sm dark:border-zinc-800 dark:bg-zinc-950/80"
                  >
                    <button
                      type="button"
                      onClick={() => {
                        setError(null);
                        setBusy(false);
                        setTranscriptId(t.id);
                      }}
                      className="w-full text-left transition hover:opacity-90"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-medium">
                          {t.ticker} {t.quarter ? <span className="text-zinc-500">· {t.quarter}</span> : null}
                        </div>
                        <div className="text-xs text-zinc-500">{t.status}</div>
                      </div>
                      {t.source_url ? (
                        <div className="mt-1 truncate text-xs text-zinc-500">{t.source_url}</div>
                      ) : null}
                    </button>
                    <div className="mt-2 flex flex-wrap gap-3 border-t border-zinc-200/80 pt-2 text-xs dark:border-zinc-800">
                      <Link
                        href={`/company/${encodeURIComponent(t.ticker)}#relevant-regulations`}
                        className="font-medium text-teal-600 hover:underline dark:text-teal-400"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Company dashboard
                      </Link>
                      <Link
                        href={`/transcripts/${t.id}`}
                        className="font-medium text-teal-600 hover:underline dark:text-teal-400"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Open transcript
                      </Link>
                    </div>
                  </div>
                ))
              ) : (
                <div className="surface-card p-4 text-sm text-zinc-600 dark:text-zinc-400">
                  None yet.
                </div>
              )}
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}
