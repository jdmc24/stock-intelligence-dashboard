"use client";

import { useEffect, useRef, useState } from "react";

import { ASK_AGENT_LABELS, ASK_TOOL_LABELS, type AskEvent } from "@/lib/ask";

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function deriveStatus(events: AskEvent[]): { label: string; step: number; total: number } {
  const plan = events.find((e) => e.type === "plan") as
    | (AskEvent & { steps?: Array<{ id: string; agent: string; status: string }> })
    | undefined;
  const steps = (plan?.steps ?? []).filter((s) => s.status !== "skipped");
  const total = Math.max(steps.length, 1);

  let step = 1;
  for (const s of steps) {
    const ended = events.some((e) => e.type === "agent_end" && e.agent === s.agent);
    const started = events.some((e) => e.type === "agent_start" && e.agent === s.agent);
    if (ended) {
      step = Math.min(total, step + 1);
    } else if (started) {
      step = Math.min(total, step + 1);
      break;
    } else {
      break;
    }
  }

  const recentMessage = [...events]
    .reverse()
    .find((e) => e.type === "message" && e.level !== "warn");
  if (recentMessage && typeof recentMessage.text === "string") {
    const text = recentMessage.text.trim();
    if (text.length > 0 && text.length < 120) {
      return { label: text, step, total };
    }
  }

  const active = [...events].reverse().find((e) => e.type === "agent_start");
  if (active) {
    const agent = ASK_AGENT_LABELS[String(active.agent)] ?? String(active.agent);
    const detail = active.label ? `: ${String(active.label)}` : "";
    return { label: `${agent}${detail}`, step, total };
  }

  if (events.some((e) => e.type === "tool_end")) {
    const lastTool = [...events].reverse().find((e) => e.type === "tool_end");
    const toolLabel = ASK_TOOL_LABELS[String(lastTool?.tool)] ?? "Running research tools";
    return { label: toolLabel, step, total };
  }

  if (events.some((e) => e.type === "plan")) {
    return { label: "Planning research steps…", step: 1, total };
  }

  return { label: "Connecting to orchestrator…", step: 1, total };
}

export function AskRunProgress({ events, running }: { events: AskEvent[]; running: boolean }) {
  const [elapsed, setElapsed] = useState(0);
  const startedAtRef = useRef<number | null>(null);
  const runId = events[0]?.run_id;

  useEffect(() => {
    if (!running) {
      startedAtRef.current = null;
      const resetId = window.setTimeout(() => setElapsed(0), 0);
      return () => window.clearTimeout(resetId);
    }
    let resetId: number | null = null;
    if (startedAtRef.current == null) {
      startedAtRef.current = Date.now();
      resetId = window.setTimeout(() => setElapsed(0), 0);
    }
    const startedAt = startedAtRef.current;
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => {
      window.clearInterval(id);
      if (resetId != null) window.clearTimeout(resetId);
    };
  }, [running, runId]);

  if (!running) return null;

  const { label, step, total } = deriveStatus(events);
  const pct = Math.min(95, Math.round((step / total) * 100));

  return (
    <div
      className="max-w-[95%] rounded-2xl border border-teal-500/20 bg-teal-500/5 px-4 py-3 dark:border-teal-500/25 dark:bg-teal-950/20"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex items-center gap-3">
        <span className="relative flex h-8 w-8 shrink-0 items-center justify-center">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-400/30" />
          <span className="relative inline-flex h-5 w-5 animate-spin rounded-full border-2 border-teal-600/30 border-t-teal-600 dark:border-teal-400/30 dark:border-t-teal-400" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-zinc-800 dark:text-zinc-100">Working on your question</p>
          <p className="mt-0.5 truncate text-xs text-zinc-600 dark:text-zinc-400">{label}</p>
        </div>
        <span className="shrink-0 font-mono text-xs text-zinc-500">{formatElapsed(elapsed)}</span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-zinc-200/80 dark:bg-zinc-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-teal-500 to-teal-400 transition-all duration-700 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-[11px] text-zinc-500">
        Step {step} of {total} · Research can take a minute while we fetch data and run tools
      </p>
    </div>
  );
}
