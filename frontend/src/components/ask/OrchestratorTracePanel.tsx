"use client";

import Link from "next/link";

import {
  ASK_AGENT_LABELS,
  ASK_TOOL_LABELS,
  type AskEvent,
} from "@/lib/ask";

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

export function OrchestratorTracePanel({
  events,
  running,
}: {
  events: AskEvent[];
  running: boolean;
}) {
  const plan = events.find((e) => e.type === "plan") as
    | (AskEvent & { steps?: Array<{ id: string; agent: string; label: string; status: string }> })
    | undefined;

  const toolEvents = events.filter((e) => e.type === "tool_start" || e.type === "tool_end");
  const toolEnds = events.filter((e) => e.type === "tool_end");

  return (
    <div className="flex h-full min-h-[420px] flex-col rounded-xl border border-zinc-200/90 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/40">
      <div className="border-b border-zinc-200/80 px-4 py-3 dark:border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Orchestrator</h2>
        <p className="mt-0.5 text-xs text-zinc-500">
          {running ? "Working on your question…" : "Run complete"}
        </p>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {plan?.steps?.length ? (
          <section>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Plan</p>
            <ol className="mt-2 space-y-2">
              {plan.steps.map((step) => (
                <li
                  key={step.id}
                  className="flex items-start gap-2 rounded-lg border border-zinc-200/80 px-3 py-2 text-xs dark:border-zinc-800"
                >
                  <span
                    className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${
                      step.status === "done"
                        ? "bg-emerald-500"
                        : step.status === "skipped"
                          ? "bg-zinc-400"
                          : step.status === "running"
                            ? "animate-pulse bg-teal-500"
                            : "bg-zinc-300 dark:bg-zinc-600"
                    }`}
                  />
                  <div>
                    <p className="font-medium text-zinc-800 dark:text-zinc-200">{step.label}</p>
                    <p className="text-zinc-500">{ASK_AGENT_LABELS[step.agent] ?? step.agent}</p>
                  </div>
                </li>
              ))}
            </ol>
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
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Tool calls</p>
            <ol className="mt-2 space-y-2">
              {toolEnds.map((e, i) => (
                <li
                  key={`tool-${e.seq}`}
                  className="rounded-lg border border-zinc-200/80 px-3 py-2 dark:border-zinc-800"
                >
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded bg-violet-500/12 px-1.5 py-0.5 font-mono text-[10px] text-violet-900 dark:text-violet-100">
                      {i + 1}
                    </span>
                    <span className="font-medium text-zinc-800 dark:text-zinc-200">
                      {ASK_TOOL_LABELS[String(e.tool)] ?? String(e.tool)}
                    </span>
                    {e.is_error ? (
                      <span className="text-red-600 dark:text-red-400">error</span>
                    ) : null}
                    {typeof e.duration_ms === "number" ? (
                      <span className="text-zinc-400">{e.duration_ms}ms</span>
                    ) : null}
                  </div>
                  <ToolOutputPreview output={e.output} />
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        {toolEvents.length === 0 && running ? (
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
