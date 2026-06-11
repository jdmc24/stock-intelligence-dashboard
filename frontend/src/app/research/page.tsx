"use client";

import { useCallback, useEffect, useState } from "react";

import { AskAnswerMarkdown } from "@/components/ask/AskAnswerMarkdown";
import {
  getAgentsStatus,
  getLatestMarketResearchBrief,
  getMarketResearchStatus,
  triggerMarketResearchBrief,
  type AgentSuiteStatus,
  type MarketResearchBrief,
  type MarketResearchStatus,
} from "@/lib/api";

function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail?: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-200/80 bg-white/65 p-3 dark:border-zinc-800 dark:bg-zinc-950/35">
      <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">{value}</p>
      {detail ? <p className="mt-1 text-xs text-zinc-500">{detail}</p> : null}
    </div>
  );
}

function BriefPanel({ brief }: { brief: MarketResearchBrief | null }) {
  if (!brief) {
    return (
      <section className="rounded-lg border border-dashed border-zinc-300/90 p-5 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
        No product-discovery brief has been generated yet.
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div className="rounded-lg border border-zinc-200/80 bg-white/70 p-5 dark:border-zinc-800 dark:bg-zinc-950/40">
        <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
          <span>{brief.brief_date}</span>
          <span>·</span>
          <span>{brief.source_item_count} source items</span>
          <span>·</span>
          <span>{brief.insight_count} relevant insights</span>
        </div>
        <h2 className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">{brief.title}</h2>
        {brief.executive_summary ? (
          <p className="mt-2 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {brief.executive_summary}
          </p>
        ) : null}
      </div>

      {brief.top_pains.length ? (
        <section>
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Top Pains</h3>
          <div className="mt-2 grid gap-3 lg:grid-cols-2">
            {brief.top_pains.map((pain, idx) => (
              <article
                key={`${pain.pain}-${idx}`}
                className="rounded-lg border border-zinc-200/80 bg-white/70 p-4 dark:border-zinc-800 dark:bg-zinc-950/40"
              >
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
                  <span>{pain.who || "unknown"}</span>
                  <span>·</span>
                  <span>{pain.evidence_count || 1} signal(s)</span>
                </div>
                <p className="mt-2 text-sm font-medium text-zinc-900 dark:text-zinc-100">{pain.pain}</p>
                {pain.why_it_matters ? (
                  <p className="mt-2 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                    {pain.why_it_matters}
                  </p>
                ) : null}
                {pain.suggested_experiment ? (
                  <p className="mt-3 rounded-md bg-teal-500/10 px-3 py-2 text-xs text-teal-900 dark:text-teal-100">
                    {pain.suggested_experiment}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {brief.suggested_experiments.length ? (
        <section className="rounded-lg border border-zinc-200/80 bg-white/70 p-4 dark:border-zinc-800 dark:bg-zinc-950/40">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Suggested Experiments</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
            {brief.suggested_experiments.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {brief.markdown ? (
        <section className="rounded-lg border border-zinc-200/80 bg-white/70 p-5 dark:border-zinc-800 dark:bg-zinc-950/40">
          <AskAnswerMarkdown content={brief.markdown} />
        </section>
      ) : null}
    </section>
  );
}

export default function ResearchPage() {
  const [status, setStatus] = useState<MarketResearchStatus | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentSuiteStatus | null>(null);
  const [brief, setBrief] = useState<MarketResearchBrief | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [nextStatus, nextBrief, nextAgentStatus] = await Promise.all([
        getMarketResearchStatus(),
        getLatestMarketResearchBrief(),
        getAgentsStatus(),
      ]);
      setStatus(nextStatus);
      setBrief(nextBrief);
      setAgentStatus(nextAgentStatus);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load product discovery data");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onTrigger() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await triggerMarketResearchBrief({ lookback_hours: 24, max_items: 40 });
      setMessage(
        `Generated ${result.title} from ${result.source_item_count} source item(s) and ${result.insight_count} insight(s).`,
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate brief");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-canvas">
      <main className="mx-auto w-full max-w-7xl px-6 py-8">
        <div className="flex flex-col gap-4 border-b border-zinc-200/80 pb-6 dark:border-zinc-800 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-teal-700 dark:text-teal-300">
              Product Discovery Agent
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Customer Signals
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
              Daily customer-discovery briefs from permitted public signals, tuned for stock-intelligence.io product ideas.
            </p>
          </div>
          <button
            type="button"
            onClick={onTrigger}
            disabled={busy}
            className="btn-primary inline-flex justify-center text-sm disabled:opacity-60"
          >
            {busy ? "Generating..." : "Generate Brief"}
          </button>
        </div>

        {error ? (
          <p className="mt-4 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
            {error}
          </p>
        ) : null}
        {message ? (
          <p className="mt-4 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-200">
            {message}
          </p>
        ) : null}

        <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Metric label="Source Items" value={status?.items ?? "—"} />
          <Metric label="Insights" value={status?.insights ?? "—"} />
          <Metric label="Briefs" value={status?.briefs ?? "—"} />
          <Metric label="RSS Feeds" value={status?.rss_feed_count ?? "—"} />
          <Metric
            label="Scheduler"
            value={status?.scheduler_enabled ? "On" : "Off"}
            detail={status?.latest_brief_date ? `Latest ${status.latest_brief_date}` : undefined}
          />
        </section>

        {agentStatus ? (
          <section className="mt-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Agent Suite</h2>
              <span className="text-xs text-zinc-500">{agentStatus.agent_count} deploy-ready agents</span>
            </div>
            <div className="mt-2 grid gap-3 lg:grid-cols-3">
              {agentStatus.agents.map((agent) => (
                <article
                  key={agent.id}
                  className="rounded-lg border border-zinc-200/80 bg-white/65 p-4 dark:border-zinc-800 dark:bg-zinc-950/35"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{agent.name}</h3>
                      <p className="mt-1 text-xs text-zinc-500">{agent.surface}</p>
                    </div>
                    <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-800 dark:text-emerald-200">
                      {agent.status}
                    </span>
                  </div>
                  {agent.sample_prompt ? (
                    <p className="mt-3 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                      {agent.sample_prompt}
                    </p>
                  ) : null}
                  <p className="mt-3 text-[11px] text-zinc-500">Smoke: {agent.smoke_script}</p>
                </article>
              ))}
            </div>
          </section>
        ) : null}

        <div className="mt-6">
          <BriefPanel brief={brief} />
        </div>
      </main>
    </div>
  );
}
