"use client";

import Link from "next/link";
import { useMemo } from "react";

import {
  ASK_AGENT_LABELS,
  ASK_TOOL_LABELS,
  ASK_TOOLS_BY_AGENT,
  type AskEvent,
} from "@/lib/ask";

type PlanStep = { id: string; agent: string; label: string; status: string };

type ToolEndEvent = AskEvent & {
  tool?: string;
  agent?: string;
  duration_ms?: number;
  is_error?: boolean;
  output?: unknown;
};

type AgentKey = "regulations" | "earnings";

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function resolveStepStatus(step: PlanStep, events: AskEvent[], running: boolean): string {
  if (step.status === "skipped") return "skipped";
  if (step.status === "done") return "done";

  const ended = events.some((e) => e.type === "agent_end" && e.agent === step.agent);
  if (ended) return "done";

  const started = events.some((e) => e.type === "agent_start" && e.agent === step.agent);
  if (started && running) return "running";
  if (started && !running) return "done";

  return step.status;
}

function stepDotClass(status: string): string {
  if (status === "done") return "bg-emerald-500";
  if (status === "skipped") return "bg-zinc-400";
  if (status === "running") return "animate-pulse bg-teal-500";
  return "bg-zinc-300 dark:bg-zinc-600";
}

function groupByTool(invocations: ToolEndEvent[]): Map<string, ToolEndEvent[]> {
  const map = new Map<string, ToolEndEvent[]>();
  for (const e of invocations) {
    const tool = String(e.tool ?? "unknown");
    const list = map.get(tool) ?? [];
    list.push(e);
    map.set(tool, list);
  }
  return map;
}

function ToolOutputPreview({ output }: { output: unknown }) {
  if (!output || typeof output !== "object") return null;
  const o = output as Record<string, unknown>;
  if (typeof o.note === "string") {
    return <p className="mt-1 text-xs text-zinc-500">{o.note}</p>;
  }
  const count = o.match_count ?? o.count;
  if (typeof count === "number") {
    return <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{count} result(s)</p>;
  }
  if (o.found === false) {
    return <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">Nothing found</p>;
  }
  return null;
}

function ToolInvocationRow({ event }: { event: ToolEndEvent }) {
  const output = event.output;
  const emptyResult =
    output &&
    typeof output === "object" &&
    ((output as Record<string, unknown>).found === false ||
      ((output as Record<string, unknown>).count === 0 &&
        (output as Record<string, unknown>).found !== true));

  return (
    <li className="rounded-md border border-zinc-200/70 bg-white/50 px-2.5 py-1.5 dark:border-zinc-800 dark:bg-zinc-950/40">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
        {event.is_error ? (
          <span className="text-red-600 dark:text-red-400">error</span>
        ) : emptyResult ? (
          <span className="text-amber-700 dark:text-amber-300">no results</span>
        ) : (
          <span className="text-emerald-700 dark:text-emerald-300">ok</span>
        )}
        {typeof event.duration_ms === "number" ? (
          <span className="ml-auto font-mono text-zinc-500">{formatDuration(event.duration_ms)}</span>
        ) : null}
      </div>
      <ToolOutputPreview output={event.output} />
    </li>
  );
}

function UsedToolGroup({ tool, invocations }: { tool: string; invocations: ToolEndEvent[] }) {
  const totalMs = invocations.reduce((s, e) => s + (e.duration_ms ?? 0), 0);
  const label = ASK_TOOL_LABELS[tool] ?? tool;
  const single = invocations.length === 1;

  if (single) {
    const e = invocations[0];
    return (
      <div className="rounded-lg border border-violet-400/30 bg-violet-500/5 px-3 py-2 dark:border-violet-700/40 dark:bg-violet-500/10">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-medium text-zinc-800 dark:text-zinc-200">{label}</span>
          {typeof e.duration_ms === "number" ? (
            <span className="ml-auto font-mono text-[11px] text-zinc-500">{formatDuration(e.duration_ms)}</span>
          ) : null}
        </div>
        <ToolOutputPreview output={e.output} />
      </div>
    );
  }

  return (
    <details className="group rounded-lg border border-violet-400/30 bg-violet-500/5 dark:border-violet-700/40 dark:bg-violet-500/10">
      <summary className="cursor-pointer list-none px-3 py-2 text-xs marker:content-none [&::-webkit-details-marker]:hidden">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-zinc-800 dark:text-zinc-200">{label}</span>
          <span className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-900 dark:text-violet-100">
            {invocations.length} calls
          </span>
          {totalMs > 0 ? (
            <span className="font-mono text-[11px] text-zinc-500">{formatDuration(totalMs)} total</span>
          ) : null}
          <span className="ml-auto text-[10px] text-zinc-400 group-open:hidden">expand</span>
        </div>
      </summary>
      <ol className="space-y-1.5 border-t border-violet-500/10 px-2 pb-2 pt-2 dark:border-violet-500/20">
        {invocations.map((e) => (
          <ToolInvocationRow key={`${e.seq}-${e.tool}`} event={e} />
        ))}
      </ol>
    </details>
  );
}

function AgentToolSection({
  agent,
  invocations,
  running,
  isActive,
}: {
  agent: AgentKey;
  invocations: ToolEndEvent[];
  running: boolean;
  isActive: boolean;
}) {
  const allTools = ASK_TOOLS_BY_AGENT[agent];
  const byTool = groupByTool(invocations);
  const calledTypes = new Set(byTool.keys());
  const unusedTools = allTools.filter((t) => !calledTypes.has(t));
  const usedCount = calledTypes.size;
  const totalMs = invocations.reduce((s, e) => s + (e.duration_ms ?? 0), 0);

  const statusLabel = isActive && running ? "Running…" : usedCount > 0 ? "Done" : running ? "Waiting…" : "Skipped";

  return (
    <section className="rounded-lg border border-zinc-200/80 dark:border-zinc-800">
      <div className="flex items-start justify-between gap-2 border-b border-zinc-200/80 px-3 py-2.5 dark:border-zinc-800">
        <div>
          <p className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">{ASK_AGENT_LABELS[agent]}</p>
          <p className="mt-0.5 text-[11px] text-zinc-500">
            {usedCount} of {allTools.length} tools used
            {totalMs > 0 ? <> · {formatDuration(totalMs)}</> : null}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
            isActive && running
              ? "bg-teal-500/15 text-teal-800 dark:text-teal-200"
              : usedCount > 0
                ? "bg-emerald-500/15 text-emerald-800 dark:text-emerald-200"
                : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800"
          }`}
        >
          {statusLabel}
        </span>
      </div>

      <div className="space-y-2 p-3">
        {isActive && running && usedCount === 0 ? (
          <p className="text-xs text-zinc-500">Starting tools…</p>
        ) : null}

        {usedCount === 0 && !running ? (
          <p className="text-xs text-zinc-500">No tools ran in this section.</p>
        ) : null}

        {[...byTool.entries()].map(([tool, calls]) => (
          <UsedToolGroup key={tool} tool={tool} invocations={calls} />
        ))}

        {unusedTools.length > 0 ? (
          <details className="rounded-lg border border-dashed border-zinc-300/80 dark:border-zinc-700">
            <summary className="cursor-pointer px-3 py-2 text-xs text-zinc-500 marker:content-none [&::-webkit-details-marker]:hidden">
              {unusedTools.length} tool{unusedTools.length === 1 ? "" : "s"} not used — click to expand
            </summary>
            <ul className="space-y-1 border-t border-zinc-200/80 px-3 py-2 dark:border-zinc-800">
              {unusedTools.map((tool) => (
                <li key={tool} className="text-[11px] text-zinc-400 dark:text-zinc-500">
                  {ASK_TOOL_LABELS[tool] ?? tool}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </section>
  );
}

export function OrchestratorTracePanel({
  events,
  running,
}: {
  events: AskEvent[];
  running: boolean;
}) {
  const plan = events.find((e) => e.type === "plan") as (AskEvent & { steps?: PlanStep[] }) | undefined;

  const toolEnds = useMemo(
    () => events.filter((e) => e.type === "tool_end") as ToolEndEvent[],
    [events],
  );

  const totalMs = useMemo(
    () => toolEnds.reduce((sum, e) => sum + (typeof e.duration_ms === "number" ? e.duration_ms : 0), 0),
    [toolEnds],
  );

  const planIncludesEarnings = (plan?.steps ?? []).some((s) => s.agent === "earnings" && s.status !== "skipped");

  const activeAgent = useMemo(() => {
    const starts = events.filter((e) => e.type === "agent_start");
    const ends = new Set(events.filter((e) => e.type === "agent_end").map((e) => String(e.agent)));
    for (let i = starts.length - 1; i >= 0; i -= 1) {
      const a = String(starts[i].agent ?? "");
      if (a === "regulations" || a === "earnings") {
        if (!ends.has(a)) return a as AgentKey;
      }
    }
    return null;
  }, [events]);

  const invocationsByAgent = useMemo(() => {
    const groups: Record<AgentKey, ToolEndEvent[]> = { regulations: [], earnings: [] };
    for (const e of toolEnds) {
      const agent = String(e.agent ?? "");
      if (agent === "regulations" || agent === "earnings") {
        groups[agent].push(e);
      }
    }
    return groups;
  }, [toolEnds]);

  const showRegulations =
    invocationsByAgent.regulations.length > 0 ||
    events.some((e) => e.agent === "regulations" && (e.type === "agent_start" || e.type === "agent_end")) ||
    (running && (plan?.steps ?? []).some((s) => s.agent === "regulations" && s.status !== "skipped"));

  const showEarnings =
    planIncludesEarnings ||
    invocationsByAgent.earnings.length > 0 ||
    events.some((e) => e.agent === "earnings" && (e.type === "agent_start" || e.type === "agent_end"));

  const resolvedSteps = (plan?.steps ?? []).map((step) => ({
    ...step,
    status: resolveStepStatus(step, events, running),
  }));

  const usedToolTypes = new Set(toolEnds.map((e) => String(e.tool)));

  return (
    <div className="flex h-full min-h-[420px] flex-col rounded-xl border border-zinc-200/90 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/40">
      <div className="border-b border-zinc-200/80 px-4 py-3 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          {running ? (
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-400/50" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-teal-500" />
            </span>
          ) : null}
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Orchestrator</h2>
        </div>
        <p className="mt-0.5 text-xs text-zinc-500">{running ? "Live trace — updates as tools run" : "Run complete"}</p>
        {toolEnds.length > 0 ? (
          <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">{usedToolTypes.size} tool types</span>
            {" · "}
            {toolEnds.length} total call{toolEnds.length === 1 ? "" : "s"}
            {totalMs > 0 ? (
              <>
                {" · "}
                <span className="font-mono">{formatDuration(totalMs)}</span>
              </>
            ) : null}
          </p>
        ) : running ? (
          <p className="mt-2 text-xs text-zinc-500">Planning and fetching data…</p>
        ) : null}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {resolvedSteps.length ? (
          <section>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Plan</p>
            <ol className="mt-2 space-y-2">
              {resolvedSteps.map((step) => (
                <li
                  key={step.id}
                  className="flex items-start gap-2 rounded-lg border border-zinc-200/80 px-3 py-2 text-xs dark:border-zinc-800"
                >
                  <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${stepDotClass(step.status)}`} />
                  <div>
                    <p className="font-medium text-zinc-800 dark:text-zinc-200">{step.label}</p>
                    <p className="text-zinc-500">{ASK_AGENT_LABELS[step.agent] ?? step.agent}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        {showRegulations ? (
          <AgentToolSection
            agent="regulations"
            invocations={invocationsByAgent.regulations}
            running={running}
            isActive={activeAgent === "regulations"}
          />
        ) : null}

        {showEarnings ? (
          <AgentToolSection
            agent="earnings"
            invocations={invocationsByAgent.earnings}
            running={running}
            isActive={activeAgent === "earnings"}
          />
        ) : null}

        {events
          .filter((e) => e.type === "message")
          .map((e) => (
            <p
              key={`msg-${e.seq}`}
              className={`rounded-lg px-3 py-2 text-xs ${
                e.level === "warn"
                  ? "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
                  : "bg-zinc-100 text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
              }`}
            >
              {String(e.text ?? "")}
            </p>
          ))}

        {toolEnds.length === 0 && running ? (
          <p className="text-xs text-zinc-500">Tools will appear here as each specialist runs.</p>
        ) : null}

        {events
          .filter((e) => e.type === "error")
          .map((e) => (
            <p key={`err-${e.seq}`} className="text-xs text-red-700 dark:text-red-300">
              {String(e.message ?? "Error")}
            </p>
          ))}
      </div>
    </div>
  );
}

export function AskCitationList({ citations }: { citations: Array<{ kind: string; label: string; href: string }> }) {
  if (!citations.length) return null;
  return (
    <ul className="mt-3 flex flex-wrap gap-2">
      {citations.map((c) => (
        <li key={`${c.kind}-${c.href}`}>
          <Link
            href={c.href}
            className="rounded-full border border-teal-500/30 bg-teal-500/10 px-2.5 py-1 text-xs text-teal-900 hover:bg-teal-500/20 dark:text-teal-100"
          >
            {c.label}
          </Link>
        </li>
      ))}
    </ul>
  );
}
