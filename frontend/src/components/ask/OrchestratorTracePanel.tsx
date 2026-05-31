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

function ToolOutputPreview({ output }: { output: unknown }) {
  if (!output || typeof output !== "object") {
    return null;
  }
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

function ToolTypeChips({
  agent,
  calledTypes,
}: {
  agent: "regulations" | "earnings";
  calledTypes: Set<string>;
}) {
  const tools = ASK_TOOLS_BY_AGENT[agent];
  const usedCount = tools.filter((t) => calledTypes.has(t)).length;

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
        {ASK_AGENT_LABELS[agent]} · {usedCount}/{tools.length} tool types used
      </p>
      <div className="flex flex-wrap gap-1.5">
        {tools.map((tool) => {
          const used = calledTypes.has(tool);
          return (
            <span
              key={tool}
              title={tool}
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                used
                  ? "bg-violet-500/15 text-violet-900 ring-1 ring-violet-500/35 dark:bg-violet-500/20 dark:text-violet-100"
                  : "bg-zinc-100 text-zinc-400 ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:text-zinc-600 dark:ring-zinc-800"
              }`}
            >
              {used ? "✓ " : ""}
              {ASK_TOOL_LABELS[tool] ?? tool}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function ToolInvocationRow({ event, index }: { event: ToolEndEvent; index: number }) {
  const output = event.output;
  const emptyResult =
    output &&
    typeof output === "object" &&
    ((output as Record<string, unknown>).found === false ||
      ((output as Record<string, unknown>).count === 0 &&
        (output as Record<string, unknown>).found !== true));

  const borderClass = event.is_error
    ? "border-red-300/80 dark:border-red-900/60"
    : emptyResult
      ? "border-amber-300/60 dark:border-amber-900/50"
      : "border-violet-400/40 dark:border-violet-700/50";

  const bgClass = event.is_error
    ? "bg-red-50/50 dark:bg-red-950/20"
    : emptyResult
      ? "bg-amber-50/40 dark:bg-amber-950/15"
      : "bg-violet-500/5 dark:bg-violet-500/10";

  return (
    <li className={`rounded-lg border-l-[3px] px-3 py-2 ${borderClass} ${bgClass}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="rounded bg-zinc-900/5 px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 dark:bg-white/10 dark:text-zinc-300">
          #{index}
        </span>
        {event.agent ? (
          <span className="rounded-full bg-teal-500/12 px-1.5 py-0.5 text-[10px] font-medium text-teal-900 dark:text-teal-100">
            {ASK_AGENT_LABELS[String(event.agent)] ?? String(event.agent)}
          </span>
        ) : null}
        <span className="font-medium text-zinc-800 dark:text-zinc-200">
          {ASK_TOOL_LABELS[String(event.tool)] ?? String(event.tool)}
        </span>
        {event.is_error ? (
          <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:text-red-300">
            error
          </span>
        ) : emptyResult ? (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:text-amber-200">
            no results
          </span>
        ) : (
          <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800 dark:text-emerald-200">
            ran
          </span>
        )}
        {typeof event.duration_ms === "number" ? (
          <span className="ml-auto font-mono text-[11px] text-zinc-500">{formatDuration(event.duration_ms)}</span>
        ) : null}
      </div>
      <ToolOutputPreview output={event.output} />
    </li>
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

  const calledTypes = useMemo(() => new Set(toolEnds.map((e) => String(e.tool ?? ""))), [toolEnds]);

  const totalMs = useMemo(
    () => toolEnds.reduce((sum, e) => sum + (typeof e.duration_ms === "number" ? e.duration_ms : 0), 0),
    [toolEnds],
  );

  const uniqueToolCount = calledTypes.size;
  const agentsUsed = useMemo(() => {
    const s = new Set<string>();
    for (const e of toolEnds) {
      if (e.agent) s.add(String(e.agent));
    }
    return s;
  }, [toolEnds]);

  const toolsByAgent = useMemo(() => {
    const groups: Record<string, ToolEndEvent[]> = { regulations: [], earnings: [] };
    for (const e of toolEnds) {
      const agent = String(e.agent ?? "unknown");
      if (!groups[agent]) groups[agent] = [];
      groups[agent].push(e);
    }
    return groups;
  }, [toolEnds]);

  const showRegToolChips = (toolsByAgent.regulations?.length ?? 0) > 0 || agentsUsed.has("regulations");
  const showEarnToolChips = (toolsByAgent.earnings?.length ?? 0) > 0 || agentsUsed.has("earnings");

  const resolvedSteps = (plan?.steps ?? []).map((step) => ({
    ...step,
    status: resolveStepStatus(step, events, running),
  }));

  return (
    <div className="flex h-full min-h-[420px] flex-col rounded-xl border border-zinc-200/90 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/40">
      <div className="border-b border-zinc-200/80 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Orchestrator</h2>
        <p className="mt-0.5 text-xs text-zinc-500">
          {running ? "Working on your question…" : "Run complete"}
        </p>
        {toolEnds.length > 0 ? (
          <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
            <span className="font-medium text-zinc-800 dark:text-zinc-200">{toolEnds.length} executions</span>
            {" · "}
            {uniqueToolCount} tool {uniqueToolCount === 1 ? "type" : "types"}
            {totalMs > 0 ? (
              <>
                {" · "}
                <span className="font-mono">{formatDuration(totalMs)}</span> total tool time
              </>
            ) : null}
          </p>
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

        {toolEnds.length > 0 ? (
          <section className="space-y-3 rounded-lg border border-zinc-200/80 bg-zinc-50/50 p-3 dark:border-zinc-800 dark:bg-zinc-900/30">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Tools used this run</p>
              <p className="mt-1 text-[11px] text-zinc-500">
                Highlighted chips were called at least once. Dim chips were not used.
              </p>
            </div>
            {showRegToolChips ? (
              <ToolTypeChips agent="regulations" calledTypes={calledTypes} />
            ) : null}
            {showEarnToolChips ? (
              <ToolTypeChips agent="earnings" calledTypes={calledTypes} />
            ) : null}
          </section>
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

        {events
          .filter((e) => e.type === "agent_start" || e.type === "agent_end")
          .map((e) => (
            <div key={`agent-${e.seq}`} className="text-xs">
              {e.type === "agent_start" ? (
                <p className="font-medium text-teal-800 dark:text-teal-300">
                  → {ASK_AGENT_LABELS[String(e.agent)] ?? String(e.agent)}
                  {e.label ? `: ${String(e.label)}` : ""}
                </p>
              ) : (
                <p className="text-zinc-500">
                  ✓ {ASK_AGENT_LABELS[String(e.agent)] ?? String(e.agent)} finished
                </p>
              )}
            </div>
          ))}

        {toolEnds.length > 0 ? (
          <section>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Execution log</p>
            <p className="mt-1 text-[11px] text-zinc-500">
              Each row is one tool call, in order. Duration is wall-clock time for that call.
            </p>
            <ol className="mt-3 space-y-2">
              {toolEnds.map((e, i) => {
                const agent = String(e.agent ?? "");
                const prevAgent = i > 0 ? String(toolEnds[i - 1].agent ?? "") : "";
                const showAgentHeader = agent && agent !== prevAgent;
                return (
                  <li key={`tool-wrap-${e.seq}`} className="list-none">
                    {showAgentHeader ? (
                      <p className="mb-2 mt-1 text-[11px] font-semibold text-zinc-700 first:mt-0 dark:text-zinc-300">
                        {ASK_AGENT_LABELS[agent] ?? agent}
                      </p>
                    ) : null}
                    <ToolInvocationRow event={e} index={i + 1} />
                  </li>
                );
              })}
            </ol>
          </section>
        ) : null}

        {toolEnds.length === 0 && running ? (
          <p className="text-xs text-zinc-500">Waiting for first tool call…</p>
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
