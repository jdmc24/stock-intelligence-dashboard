"use client";

import { useState } from "react";

import type { Analysis } from "@/lib/api";
import { formatTranscriptSectionLabel } from "@/lib/transcriptLabels";

type TabId = "overview" | "sentiment" | "hedging" | "guidance" | "topics";

const tabs: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "sentiment", label: "Sentiment" },
  { id: "hedging", label: "Hedging" },
  { id: "guidance", label: "Guidance" },
  { id: "topics", label: "Topics" },
];

export function FormattedAnalysis({ data }: { data: Analysis }) {
  const [tab, setTab] = useState<TabId>("overview");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 border-b border-zinc-200 pb-2 dark:border-zinc-800">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" ? <OverviewTab data={data} /> : null}
      {tab === "sentiment" ? <SentimentTab sentiment={data.sentiment} /> : null}
      {tab === "hedging" ? <HedgingTab hedging={data.hedging} /> : null}
      {tab === "guidance" ? <GuidanceTab guidance={data.guidance} /> : null}
      {tab === "topics" ? <TopicsTab topics={data.topics} /> : null}
    </div>
  );
}

function OverviewTab({ data }: { data: Analysis }) {
  return (
    <div className="space-y-4">
      {data.summary ? (
        <section className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Executive summary</h2>
          <p className="mt-2 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{data.summary}</p>
        </section>
      ) : (
        <p className="text-sm text-zinc-500">No summary returned.</p>
      )}
      {data.model_used ? (
        <p className="text-xs text-zinc-500">
          Model: <span className="font-mono">{data.model_used}</span>
        </p>
      ) : null}
    </div>
  );
}

function SentimentTab({ sentiment }: { sentiment: Record<string, unknown> | null }) {
  if (!sentiment || typeof sentiment !== "object") {
    return <Empty />;
  }

  const overall = typeof sentiment.overall_tone === "string" ? sentiment.overall_tone : null;
  const sections = Array.isArray(sentiment.sections) ? sentiment.sections : [];

  return (
    <div className="space-y-4">
      {overall ? (
        <p className="text-sm">
          <span className="font-medium text-zinc-800 dark:text-zinc-200">Overall tone: </span>
          <span className="rounded-md bg-zinc-100 px-2 py-0.5 font-mono text-xs text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200">
            {overall}
          </span>
        </p>
      ) : null}

      {sections.map((raw, i) => {
        const s = raw as Record<string, unknown>;
        const sec = typeof s.section === "string" ? s.section : "section";
        const speaker = typeof s.speaker === "string" ? s.speaker : null;
        const sent = s.sentiment as Record<string, unknown> | undefined;
        const quotes = Array.isArray(s.notable_quotes) ? s.notable_quotes : [];

        return (
          <div
            key={i}
            className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950"
          >
            <div className="flex flex-wrap items-baseline gap-2 text-sm">
              <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                {formatTranscriptSectionLabel(sec)}
              </span>
              {speaker ? <span className="text-zinc-500">· {speaker}</span> : null}
            </div>
            {sent ? (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {(["confidence", "defensiveness", "specificity", "urgency"] as const).map((k) => {
                  const v = sent[k];
                  const n = typeof v === "number" ? v : null;
                  if (n === null) return null;
                  return (
                    <div key={k}>
                      <div className="flex justify-between text-xs text-zinc-500">
                        <span className="capitalize">{k}</span>
                        <span>{n.toFixed(2)}</span>
                      </div>
                      <Meter value={n} />
                    </div>
                  );
                })}
                {typeof sent.overall === "string" ? (
                  <div className="sm:col-span-2 text-xs text-zinc-600 dark:text-zinc-400">
                    Section tone: <em>{sent.overall}</em>
                  </div>
                ) : null}
              </div>
            ) : null}
            {quotes.length > 0 ? (
              <ul className="mt-3 space-y-2 border-t border-zinc-100 pt-3 dark:border-zinc-800">
                {quotes.map((q, j) => {
                  const quote = q as Record<string, unknown>;
                  const text = typeof quote.text === "string" ? quote.text : "";
                  const signal = typeof quote.signal === "string" ? quote.signal : "";
                  const ctx = typeof quote.context === "string" ? quote.context : "";
                  if (!text) return null;
                  return (
                    <li key={j} className="text-sm">
                      <blockquote className="border-l-2 border-zinc-300 pl-3 italic text-zinc-700 dark:border-zinc-600 dark:text-zinc-300">
                        “{text}”
                      </blockquote>
                      {(signal || ctx) && (
                        <p className="mt-1 text-xs text-zinc-500">
                          {signal ? <span className="font-medium">{signal}</span> : null}
                          {signal && ctx ? " · " : null}
                          {ctx}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function HedgingTab({ hedging }: { hedging: Record<string, unknown> | null }) {
  if (!hedging || typeof hedging !== "object") {
    return <Empty />;
  }

  const instances = Array.isArray(hedging.hedging_instances) ? hedging.hedging_instances : [];
  const score = typeof hedging.hedging_score === "number" ? hedging.hedging_score : null;
  const trend = typeof hedging.hedging_trend === "string" ? hedging.hedging_trend : null;

  return (
    <div className="space-y-4">
      {(score !== null || trend) && (
        <div className="flex flex-wrap gap-4 text-sm">
          {score !== null ? (
            <div>
              <span className="text-zinc-500">Hedging score: </span>
              <span className="font-mono font-medium">{score.toFixed(2)}</span>
              <Meter value={score} className="mt-1 max-w-xs" />
            </div>
          ) : null}
          {trend ? (
            <div>
              <span className="text-zinc-500">Trend: </span>
              <span className="rounded-md bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
                {trend}
              </span>
            </div>
          ) : null}
        </div>
      )}

      {instances.length === 0 ? (
        <p className="text-sm text-zinc-500">No hedging instances flagged.</p>
      ) : (
        <ul className="space-y-3">
          {instances.map((raw, i) => {
            const h = raw as Record<string, unknown>;
            const text = typeof h.text === "string" ? h.text : "";
            const category = typeof h.category === "string" ? h.category : "other";
            const severity = typeof h.severity === "string" ? h.severity : "";
            const note = typeof h.note === "string" ? h.note : "";
            return (
              <li
                key={i}
                className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950"
              >
                <div className="flex flex-wrap gap-2">
                  <span className="rounded bg-zinc-100 px-2 py-0.5 font-mono text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                    {category.replace(/_/g, " ")}
                  </span>
                  {severity ? (
                    <span className="text-xs text-zinc-500">Severity: {severity}</span>
                  ) : null}
                </div>
                <p className="mt-2 text-sm text-zinc-800 dark:text-zinc-200">{text}</p>
                {note ? <p className="mt-1 text-xs text-zinc-500">{note}</p> : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function GuidanceTab({ guidance }: { guidance: Record<string, unknown> | null }) {
  if (!guidance || typeof guidance !== "object") {
    return <Empty />;
  }

  const items = Array.isArray(guidance.guidance) ? guidance.guidance : [];

  if (items.length === 0) {
    return <p className="text-sm text-zinc-500">No guidance statements extracted.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="border-b border-zinc-200 bg-zinc-50 text-xs font-medium text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-3 py-2">Metric</th>
            <th className="px-3 py-2">Direction</th>
            <th className="px-3 py-2">Timeframe</th>
            <th className="px-3 py-2">Speaker</th>
            <th className="px-3 py-2">Excerpt</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {items.map((raw, i) => {
            const g = raw as Record<string, unknown>;
            return (
              <tr key={i} className="bg-white dark:bg-zinc-950">
                <td className="px-3 py-2 font-medium text-zinc-900 dark:text-zinc-100">
                  {String(g.metric ?? "—")}
                </td>
                <td className="px-3 py-2 capitalize text-zinc-700 dark:text-zinc-300">
                  {String(g.direction ?? "—")}
                </td>
                <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
                  {String(g.timeframe ?? "—")}
                </td>
                <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
                  {String(g.speaker ?? "—")}
                </td>
                <td className="max-w-md px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400">
                  {String(g.source_text ?? "").slice(0, 280)}
                  {String(g.source_text ?? "").length > 280 ? "…" : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TopicsTab({ topics }: { topics: Record<string, unknown> | null }) {
  if (!topics || typeof topics !== "object") {
    return <Empty />;
  }

  const items = Array.isArray(topics.topics) ? topics.topics : [];

  if (items.length === 0) {
    return <p className="text-sm text-zinc-500">No topics tagged.</p>;
  }

  return (
    <ul className="space-y-3">
      {items.map((raw, i) => {
        const t = raw as Record<string, unknown>;
        const topic = typeof t.topic === "string" ? t.topic : "Topic";
        const rel = typeof t.relevance === "number" ? t.relevance : null;
        const evidence = typeof t.evidence === "string" ? t.evidence : "";
        return (
          <li
            key={i}
            className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-zinc-900 dark:text-zinc-100">{topic}</span>
              {rel !== null ? (
                <span className="text-xs text-zinc-500">Relevance: {rel.toFixed(2)}</span>
              ) : null}
            </div>
            {rel !== null ? <Meter value={rel} className="mt-2 max-w-xs" /> : null}
            {evidence ? <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">{evidence}</p> : null}
          </li>
        );
      })}
    </ul>
  );
}

function Meter({ value, className = "" }: { value: number; className?: string }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  return (
    <div className={`h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800 ${className}`}>
      <div
        className="h-full rounded-full bg-zinc-700 transition-[width] dark:bg-zinc-300"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function Empty() {
  return <p className="text-sm text-zinc-500">No data for this section.</p>;
}
