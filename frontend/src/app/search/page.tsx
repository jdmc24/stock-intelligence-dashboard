"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { API_BASE, searchQuotes, searchTranscripts, type QuoteHit, type SearchHit } from "@/lib/api";
import { formatTranscriptSectionLabel } from "@/lib/transcriptLabels";

export default function SearchPage() {
  const [company, setCompany] = useState("");
  const [topic, setTopic] = useState("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [transcriptBusy, setTranscriptBusy] = useState(false);

  const [quoteQuery, setQuoteQuery] = useState("");
  const [quoteCompany, setQuoteCompany] = useState("");
  const [quotes, setQuotes] = useState<QuoteHit[] | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quoteBusy, setQuoteBusy] = useState(false);

  const runTranscriptSearch = useCallback(async () => {
    const c = company.trim();
    const t = topic.trim();
    const kw = q.trim();
    if (!c && !t && !kw) {
      setTranscriptError("Enter a ticker, topic phrase, and/or keyword (at least one).");
      return;
    }
    setTranscriptError(null);
    setTranscriptBusy(true);
    setHits(null);
    try {
      const data = await searchTranscripts({ company: c || undefined, topic: t || undefined, q: kw || undefined });
      setHits(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Search failed";
      setTranscriptError(
        msg === "Failed to fetch" || msg.includes("fetch")
          ? `${msg} — check API at ${API_BASE}`
          : msg,
      );
    } finally {
      setTranscriptBusy(false);
    }
  }, [company, topic, q]);

  const runQuoteSearch = useCallback(async () => {
    const qq = quoteQuery.trim();
    if (qq.length < 2) {
      setQuoteError("Quote search needs at least 2 characters.");
      return;
    }
    setQuoteError(null);
    setQuoteBusy(true);
    setQuotes(null);
    try {
      const data = await searchQuotes(qq, quoteCompany.trim() || undefined);
      setQuotes(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Search failed";
      setQuoteError(
        msg === "Failed to fetch" || msg.includes("fetch")
          ? `${msg} — check API at ${API_BASE}`
          : msg,
      );
    } finally {
      setQuoteBusy(false);
    }
  }, [quoteQuery, quoteCompany]);

  return (
    <div className="page-canvas">
      <main className="mx-auto max-w-5xl space-y-12 px-6 py-10">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
            Full-text search
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
            Search transcripts
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Full-text search over stored transcripts and parsed sections (local SQLite). Matches are case-insensitive.
          </p>
        </div>

        <section className="surface-card p-5 sm:p-6">
          <h2 className="text-lg font-semibold">Transcripts</h2>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Filter by ticker and/or require phrases in the raw transcript body (PRD: <code className="font-mono text-xs">company</code>,{" "}
            <code className="font-mono text-xs">topic</code>).
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div>
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Company (ticker)</label>
              <input
                value={company}
                onChange={(e) => setCompany(e.target.value.toUpperCase())}
                placeholder="AAPL"
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Topic / phrase in text</label>
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="AI investment"
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Keyword (alias)</label>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="margin"
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              />
            </div>
          </div>
          <button
            type="button"
            onClick={runTranscriptSearch}
            disabled={transcriptBusy}
            className="btn-primary mt-4"
          >
            {transcriptBusy ? "Searching…" : "Search transcripts"}
          </button>
          {transcriptError ? (
            <p className="mt-3 text-sm text-red-700 dark:text-red-300">{transcriptError}</p>
          ) : null}
          {hits ? (
            <ul className="mt-6 space-y-3">
              {hits.length === 0 ? (
                <li className="text-sm text-zinc-600 dark:text-zinc-400">No matches.</li>
              ) : (
                hits.map((h) => (
                  <li
                    key={h.transcript_id}
                    className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div className="font-medium">
                        {h.ticker}
                        {h.quarter ? <span className="text-zinc-500"> · {h.quarter}</span> : null}
                        <span className="ml-2 text-xs font-normal text-zinc-500">{h.status}</span>
                      </div>
                      <div className="flex flex-wrap gap-3">
                        <Link
                          href={`/transcripts/${h.transcript_id}`}
                          className="text-xs font-medium text-zinc-900 underline dark:text-zinc-100"
                        >
                          View transcript
                        </Link>
                        <Link
                          href={`/analysis/${h.transcript_id}`}
                          className="text-xs font-medium text-zinc-900 underline dark:text-zinc-100"
                        >
                          Analyze with Claude
                        </Link>
                      </div>
                    </div>
                    {h.company_name ? (
                      <p className="mt-1 text-xs text-zinc-500">{h.company_name}</p>
                    ) : null}
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
                      {h.snippet}
                    </p>
                  </li>
                ))
              )}
            </ul>
          ) : null}
        </section>

        <section className="surface-card p-5 sm:p-6">
          <h2 className="text-lg font-semibold">Quotes in sections</h2>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Find parsed sections (speaker lines) containing your phrase — e.g. credit quality, guidance language.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-1">
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Query</label>
              <input
                value={quoteQuery}
                onChange={(e) => setQuoteQuery(e.target.value)}
                placeholder="credit quality"
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Ticker (optional)</label>
              <input
                value={quoteCompany}
                onChange={(e) => setQuoteCompany(e.target.value.toUpperCase())}
                placeholder="JPM"
                className="mt-1 w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none ring-teal-500/0 transition focus:border-teal-500/50 focus:ring-2 focus:ring-teal-500/30 dark:border-zinc-700 dark:bg-zinc-900/80"
              />
            </div>
          </div>
          <button
            type="button"
            onClick={runQuoteSearch}
            disabled={quoteBusy}
            className="btn-primary mt-4"
          >
            {quoteBusy ? "Searching…" : "Search quotes"}
          </button>
          {quoteError ? <p className="mt-3 text-sm text-red-700 dark:text-red-300">{quoteError}</p> : null}
          {quotes ? (
            <ul className="mt-6 space-y-3">
              {quotes.length === 0 ? (
                <li className="text-sm text-zinc-600 dark:text-zinc-400">No matching sections.</li>
              ) : (
                quotes.map((row, i) => (
                  <li
                    key={`${row.transcript_id}-${row.order}-${i}`}
                    className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                        {row.ticker}
                        {row.quarter ? <> · {row.quarter}</> : null} · {formatTranscriptSectionLabel(row.section_type)}
                        {row.speaker ? <> · {row.speaker}</> : null}
                      </div>
                      <Link
                        href={`/transcripts/${row.transcript_id}`}
                        className="text-xs font-medium text-zinc-900 underline dark:text-zinc-100"
                      >
                        View transcript
                      </Link>
                    </div>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
                      {row.excerpt}
                    </p>
                  </li>
                ))
              )}
            </ul>
          ) : null}
        </section>
      </main>
    </div>
  );
}
