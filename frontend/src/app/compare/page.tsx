"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import {
  API_BASE,
  compareAnalyses,
  getCompanyTimeline,
  listTranscripts,
  type CompanyTimeline,
  type ComparisonResponse,
  type Transcript,
} from "@/lib/api";

function parseApiDate(s: string | null): Date | null {
  if (!s?.trim()) return null;
  const raw = s.includes("T") ? s : `${s}T12:00:00Z`;
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Distinguish rows when quarter label is missing (e.g. “most recent” fetch). */
function transcriptPeriodSubtitle(t: Transcript): string {
  const call = parseApiDate(t.call_date);
  if (call) {
    return `Call · ${call.toLocaleDateString(undefined, { dateStyle: "medium" })}`;
  }
  const proc = parseApiDate(t.processed_at);
  if (proc) {
    return `Stored · ${proc.toLocaleDateString(undefined, { dateStyle: "medium" })}`;
  }
  const created = parseApiDate(t.created_at);
  if (created) {
    return `Added · ${created.toLocaleDateString(undefined, { dateStyle: "medium" })}`;
  }
  return "";
}

function compareTranscriptsChronological(a: Transcript, b: Transcript): number {
  const ca = parseApiDate(a.call_date)?.getTime() ?? 0;
  const cb = parseApiDate(b.call_date)?.getTime() ?? 0;
  if (ca !== cb) return ca - cb;
  const pa = parseApiDate(a.processed_at)?.getTime() ?? 0;
  const pb = parseApiDate(b.processed_at)?.getTime() ?? 0;
  if (pa !== pb) return pa - pb;
  return (
    (parseApiDate(a.created_at)?.getTime() ?? 0) - (parseApiDate(b.created_at)?.getTime() ?? 0)
  );
}

function MiniBars({ values, label }: { values: number[]; label: string }) {
  const max = Math.max(...values, 1e-6);
  return (
    <div>
      <div className="mb-1 text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="flex h-10 items-end gap-0.5 rounded-lg bg-zinc-100 p-1 dark:bg-zinc-900">
        {values.map((v, i) => (
          <div
            key={i}
            title={v.toFixed(2)}
            className="min-w-[6px] flex-1 rounded-sm bg-teal-500/80 dark:bg-teal-500/70"
            style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
          />
        ))}
      </div>
    </div>
  );
}

function ComparisonView({ data }: { data: ComparisonResponse }) {
  const c = data.comparison;
  const summary =
    typeof c.executive_summary === "string" ? c.executive_summary : null;
  const hedging = typeof c.hedging_shift === "string" ? c.hedging_shift : null;
  const shifts = Array.isArray(c.key_shifts) ? c.key_shifts : [];
  const newTopics = Array.isArray(c.new_topics) ? c.new_topics : [];
  const dropped = Array.isArray(c.dropped_topics) ? c.dropped_topics : [];
  const guidance = Array.isArray(c.guidance_changes) ? c.guidance_changes : [];
  const qa = Array.isArray(c.qa_highlights) ? c.qa_highlights : [];

  return (
    <div className="space-y-6">
      {summary ? (
        <section className="surface-card p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Executive summary</h2>
          <p className="mt-2 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{summary}</p>
        </section>
      ) : null}

      {hedging ? (
        <section className="surface-card p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Hedging shift</h2>
          <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">{hedging}</p>
        </section>
      ) : null}

      {newTopics.length || dropped.length ? (
        <section className="surface-card p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Topic churn</h2>
          <div className="mt-2 flex flex-wrap gap-2">
            {newTopics.map((t: unknown) =>
              typeof t === "string" ? (
                <span
                  key={`n-${t}`}
                  className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200"
                >
                  + {t}
                </span>
              ) : null,
            )}
            {dropped.map((t: unknown) =>
              typeof t === "string" ? (
                <span
                  key={`d-${t}`}
                  className="rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-900 dark:bg-rose-950/50 dark:text-rose-200"
                >
                  − {t}
                </span>
              ) : null,
            )}
          </div>
        </section>
      ) : null}

      {shifts.length ? (
        <section className="surface-card p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Key shifts</h2>
          <ul className="mt-3 space-y-4">
            {shifts.map((row: unknown, i: number) => {
              if (!row || typeof row !== "object") return null;
              const r = row as Record<string, unknown>;
              const topic = typeof r.topic === "string" ? r.topic : "Topic";
              const ev = typeof r.evidence === "string" ? r.evidence : "";
              const interp = typeof r.interpretation === "string" ? r.interpretation : "";
              const earlier = typeof r.earlier_tone === "string" ? r.earlier_tone : null;
              const later = typeof r.later_tone === "string" ? r.later_tone : null;
              return (
                <li key={i} className="border-l-2 border-zinc-300 pl-3 dark:border-zinc-600">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">{topic}</div>
                  {earlier && later ? (
                    <p className="mt-1 text-xs text-zinc-500">
                      {earlier} → {later}
                    </p>
                  ) : null}
                  {ev ? (
                    <blockquote className="mt-2 text-sm italic text-zinc-700 dark:text-zinc-300">&ldquo;{ev}&rdquo;</blockquote>
                  ) : null}
                  {interp ? <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">{interp}</p> : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {guidance.length ? (
        <section className="surface-card p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Guidance changes</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-700">
                  <th className="py-2 pr-2">Metric</th>
                  <th className="py-2 pr-2">Earlier</th>
                  <th className="py-2 pr-2">Later</th>
                  <th className="py-2 pr-2">Change</th>
                </tr>
              </thead>
              <tbody>
                {guidance.map((row: unknown, i: number) => {
                  if (!row || typeof row !== "object") return null;
                  const r = row as Record<string, unknown>;
                  return (
                    <tr key={i} className="border-b border-zinc-100 dark:border-zinc-800">
                      <td className="py-2 pr-2 font-medium">{String(r.metric ?? "—")}</td>
                      <td className="py-2 pr-2 text-zinc-600">{String(r.earlier_guidance ?? "—")}</td>
                      <td className="py-2 pr-2 text-zinc-600">{String(r.later_guidance ?? "—")}</td>
                      <td className="py-2 pr-2">{String(r.change ?? "—")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {qa.length ? (
        <section className="surface-card p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{"Q&A highlights"}</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
            {qa.map((q: unknown, i: number) =>
              typeof q === "string" ? <li key={i}>{q}</li> : null,
            )}
          </ul>
        </section>
      ) : null}

      <p className="text-xs text-zinc-500">
        Model: <span className="font-mono">{data.model_used}</span>
      </p>
    </div>
  );
}

function TimelineSection({
  tickerInput,
  onTickerInput,
  onLoad,
  timeline,
  timelineError,
  timelineLoading,
}: {
  tickerInput: string;
  onTickerInput: (v: string) => void;
  onLoad: () => void;
  timeline: CompanyTimeline | null;
  timelineError: string | null;
  timelineLoading: boolean;
}) {
  const hedgingVals = useMemo(
    () => (timeline?.points ?? []).map((p) => p.hedging_score ?? 0),
    [timeline],
  );
  const guideVals = useMemo(
    () => (timeline?.points ?? []).map((p) => p.guidance_count ?? 0),
    [timeline],
  );

  return (
    <section className="surface-card p-4 sm:p-5">
      <h2 className="text-lg font-semibold">Company timeline</h2>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
        Sentiment label, hedging score, and guidance density across analyzed quarters (same ticker).
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <div>
          <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Ticker</label>
          <input
            value={tickerInput}
            onChange={(e) => onTickerInput(e.target.value.toUpperCase())}
            className="mt-1 w-40 rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-400 dark:border-zinc-800 dark:bg-black"
            placeholder="AAPL"
          />
        </div>
        <button
          type="button"
          onClick={onLoad}
          disabled={timelineLoading || !tickerInput.trim()}
          className="rounded-xl bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
        >
          {timelineLoading ? "Loading…" : "Load timeline"}
        </button>
      </div>
      {timelineError ? (
        <p className="mt-3 text-sm text-red-700 dark:text-red-300">{timelineError}</p>
      ) : null}
      {timeline && timeline.points.length ? (
        <div className="mt-6 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <MiniBars values={hedgingVals} label="Hedging score (by quarter, chronological)" />
            <MiniBars values={guideVals} label="Guidance statements count" />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-700">
                  <th className="py-2 pr-2">Quarter</th>
                  <th className="py-2 pr-2">Tone</th>
                  <th className="py-2 pr-2">Hedging</th>
                  <th className="py-2 pr-2">Guidance #</th>
                  <th className="py-2 pr-2">Top topics</th>
                  <th className="py-2 pr-2" />
                </tr>
              </thead>
              <tbody>
                {timeline.points.map((p) => (
                  <tr key={p.transcript_id} className="border-b border-zinc-100 dark:border-zinc-800">
                    <td className="py-2 pr-2 font-mono text-xs">
                      {p.quarter ?? "—"}
                      {p.call_date ? (
                        <span className="block text-zinc-500">{p.call_date}</span>
                      ) : null}
                    </td>
                    <td className="py-2 pr-2 text-zinc-700 dark:text-zinc-300">{p.overall_tone ?? "—"}</td>
                    <td className="py-2 pr-2">{p.hedging_score ?? "—"}</td>
                    <td className="py-2 pr-2">{p.guidance_count}</td>
                    <td className="py-2 pr-2 text-xs text-zinc-600 dark:text-zinc-400">
                      {p.top_topics.slice(0, 4).join(", ") || "—"}
                    </td>
                    <td className="py-2 pr-2 text-right">
                      <Link
                        href={`/analysis/${p.transcript_id}`}
                        className="text-xs font-medium text-zinc-900 underline dark:text-zinc-100"
                      >
                        Analysis
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : timeline && !timeline.points.length ? (
        <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
          No completed analyses for this ticker yet. Fetch transcripts on Home and use &ldquo;Analyze with Claude&rdquo; for each quarter.
        </p>
      ) : null}
    </section>
  );
}

function CompareInner() {
  const searchParams = useSearchParams();
  const idsFromUrl = useMemo(() => {
    const raw = searchParams.get("ids");
    if (!raw) return [] as string[];
    return raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }, [searchParams]);

  const [compareTranscripts, setCompareTranscripts] = useState<Transcript[]>([]);
  const [compareListLoading, setCompareListLoading] = useState(false);
  const [compareListError, setCompareListError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [compareResult, setCompareResult] = useState<ComparisonResponse | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [compareBusy, setCompareBusy] = useState(false);

  const [tickerInput, setTickerInput] = useState("AAPL");
  const [timeline, setTimeline] = useState<CompanyTimeline | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);

  useEffect(() => {
    if (idsFromUrl.length) {
      setSelected(new Set(idsFromUrl));
    }
  }, [idsFromUrl]);

  useEffect(() => {
    const t = tickerInput.trim().toUpperCase();
    if (!t) {
      setCompareTranscripts([]);
      return;
    }
    let cancelled = false;
    setCompareListLoading(true);
    setCompareListError(null);
    listTranscripts({ ticker: t, status: "analyzed", limit: 100 })
      .then((rows) => {
        if (!cancelled) setCompareTranscripts(rows);
      })
      .catch((e) => {
        if (!cancelled) {
          setCompareTranscripts([]);
          setCompareListError(e instanceof Error ? e.message : "Failed to load transcripts");
        }
      })
      .finally(() => {
        if (!cancelled) setCompareListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tickerInput]);

  const sortedCompareTranscripts = useMemo(
    () => [...compareTranscripts].sort(compareTranscriptsChronological),
    [compareTranscripts],
  );

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const runCompare = useCallback(async () => {
    const ids = [...selected];
    if (ids.length < 2) {
      setCompareError("Select at least two analyzed transcripts (same company).");
      return;
    }
    setCompareError(null);
    setCompareBusy(true);
    setCompareResult(null);
    try {
      const res = await compareAnalyses({ transcript_ids: ids });
      setCompareResult(res);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Compare failed";
      const hint =
        msg === "Failed to fetch" || msg.includes("fetch")
          ? ` Cannot reach API at ${API_BASE}.`
          : "";
      setCompareError(msg + hint);
    } finally {
      setCompareBusy(false);
    }
  }, [selected]);

  const loadTimeline = useCallback(async () => {
    const t = tickerInput.trim().toUpperCase();
    if (!t) return;
    setTimelineError(null);
    setTimelineLoading(true);
    setTimeline(null);
    try {
      const tl = await getCompanyTimeline(t);
      setTimeline(tl);
    } catch (e) {
      setTimelineError(e instanceof Error ? e.message : "Failed to load timeline");
    } finally {
      setTimelineLoading(false);
    }
  }, [tickerInput]);

  return (
    <div className="page-canvas">
      <main className="mx-auto max-w-5xl space-y-10 px-6 py-10">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
            Quarters &amp; AI diff
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
            Compare &amp; timeline
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Cross-quarter comparison uses completed AI analysis JSON (not raw transcripts). Pick two or more calls from the same ticker.
          </p>
        </div>

        <TimelineSection
          tickerInput={tickerInput}
          onTickerInput={setTickerInput}
          onLoad={loadTimeline}
          timeline={timeline}
          timelineError={timelineError}
          timelineLoading={timelineLoading}
        />

        <section className="surface-card p-5 sm:p-6">
          <h2 className="text-lg font-semibold">Quarter-over-quarter comparison</h2>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Uses the <strong className="font-medium text-zinc-800 dark:text-zinc-200">ticker in the timeline section above</strong> (
            <span className="font-mono">{tickerInput.trim().toUpperCase() || "—"}</span>
            ). Check two or more analyzed quarters, then run compare. URL{' '}
            <code className="rounded bg-zinc-100 px-1 font-mono text-xs dark:bg-zinc-900">?ids=id1,id2</code> pre-selects rows.
          </p>

          {compareListLoading ? (
            <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">Loading analyzed transcripts for this ticker…</p>
          ) : null}
          {compareListError ? (
            <p className="mt-4 text-sm text-red-700 dark:text-red-300">{compareListError}</p>
          ) : null}

          {!compareListLoading && sortedCompareTranscripts.length ? (
            <ul className="mt-4 space-y-2">
              {sortedCompareTranscripts.map((t) => {
                const periodLine = transcriptPeriodSubtitle(t);
                return (
                <li key={t.id}>
                  <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-zinc-200 p-3 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900/40">
                    <input
                      type="checkbox"
                      checked={selected.has(t.id)}
                      onChange={() => toggle(t.id)}
                      className="mt-1"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">
                        {t.ticker}
                        {t.quarter?.trim() ? (
                          <span className="text-zinc-500 dark:text-zinc-400"> · {t.quarter.trim()}</span>
                        ) : null}
                      </div>
                      {periodLine ? (
                        <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{periodLine}</div>
                      ) : null}
                    </div>
                    <Link
                      href={`/analysis/${t.id}`}
                      className="shrink-0 text-xs font-medium text-zinc-900 underline dark:text-zinc-100"
                      onClick={(e) => e.stopPropagation()}
                    >
                      Open
                    </Link>
                  </label>
                </li>
              );
              })}
            </ul>
          ) : !compareListLoading && !compareListError ? (
            <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
              No analyzed transcripts for ticker{" "}
              <span className="font-mono">{tickerInput.trim().toUpperCase() || "—"}</span>. On Home, fetch that ticker&rsquo;s calls,
              run &ldquo;Analyze with Claude&rdquo; on each, then return here (or change the ticker above to match).
            </p>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={runCompare}
              disabled={compareBusy || selected.size < 2}
              className="btn-primary"
            >
              {compareBusy ? "Comparing…" : "Run comparison"}
            </button>
            <span className="self-center text-xs text-zinc-500">{selected.size} selected</span>
          </div>

          {compareError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-200">
              {compareError}
            </div>
          ) : null}

          {compareResult ? (
            <div className="mt-6">
              <ComparisonView data={compareResult} />
            </div>
          ) : null}
        </section>
      </main>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <div className="page-canvas px-6 py-10">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
        </div>
      }
    >
      <CompareInner />
    </Suspense>
  );
}
