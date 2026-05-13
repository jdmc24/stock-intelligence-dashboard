"use client";

import Link from "next/link";
import { useId, useState } from "react";

import type { RegToolCall } from "@/lib/api";

/** Pretty rendering for the two tools we currently expose to Claude during
 * enrichment. Falls back to a JSON view for anything else. */
function ToolCallBody({ call }: { call: RegToolCall }) {
  const input = call.input ?? {};
  const output = call.output ?? {};

  if (call.is_error) {
    return (
      <p className="font-mono text-xs text-red-700 dark:text-red-300">
        {typeof (output as { error?: unknown }).error === "string"
          ? String((output as { error?: string }).error)
          : "Tool error"}
      </p>
    );
  }

  if (call.name === "search_related_regulations") {
    const query = typeof input.query === "string" ? input.query : "";
    const matches = Array.isArray((output as { matches?: unknown }).matches)
      ? ((output as { matches: Array<Record<string, unknown>> }).matches)
      : [];
    return (
      <div className="space-y-2">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Query: <span className="font-mono text-zinc-700 dark:text-zinc-300">{query || "(empty)"}</span>
        </p>
        {matches.length === 0 ? (
          <p className="text-xs italic text-zinc-500 dark:text-zinc-400">No related documents found.</p>
        ) : (
          <ul className="space-y-1.5">
            {matches.map((m, i) => {
              const id = typeof m.id === "string" ? m.id : null;
              const title = typeof m.title === "string" ? m.title : "(untitled)";
              const date = typeof m.publication_date === "string" ? m.publication_date : "";
              const severity = typeof m.severity === "string" ? m.severity : null;
              return (
                <li key={id ?? i} className="text-xs leading-relaxed">
                  {id ? (
                    <Link
                      href={`/regulations/${id}`}
                      className="font-medium text-teal-700 hover:underline dark:text-teal-400"
                    >
                      {title}
                    </Link>
                  ) : (
                    <span className="font-medium text-zinc-700 dark:text-zinc-300">{title}</span>
                  )}
                  <span className="ml-2 text-zinc-500">{date}</span>
                  {severity ? (
                    <span className="ml-2 rounded bg-zinc-200/70 px-1.5 py-0.5 font-mono text-[10px] uppercase text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                      {severity}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  if (call.name === "lookup_company_profile") {
    const ticker = typeof input.ticker === "string" ? input.ticker : "";
    const found = (output as { found?: unknown }).found === true;
    if (!found) {
      return (
        <p className="text-xs text-zinc-600 dark:text-zinc-400">
          No profile for <span className="font-mono">{ticker || "(empty)"}</span> in the database.
        </p>
      );
    }
    const name = typeof (output as { name?: unknown }).name === "string" ? String((output as { name: string }).name) : "";
    const products = Array.isArray((output as { primary_products?: unknown }).primary_products)
      ? ((output as { primary_products: string[] }).primary_products)
      : [];
    const functions = Array.isArray((output as { primary_functions?: unknown }).primary_functions)
      ? ((output as { primary_functions: string[] }).primary_functions)
      : [];
    return (
      <div className="space-y-1.5 text-xs">
        <p>
          <span className="font-mono text-zinc-700 dark:text-zinc-300">{ticker}</span>
          {name ? <span className="text-zinc-500"> · {name}</span> : null}
        </p>
        {products.length > 0 ? (
          <p>
            <span className="text-zinc-500">Products:</span>{" "}
            <span className="text-zinc-700 dark:text-zinc-300">{products.join(", ")}</span>
          </p>
        ) : null}
        {functions.length > 0 ? (
          <p>
            <span className="text-zinc-500">Functions:</span>{" "}
            <span className="text-zinc-700 dark:text-zinc-300">{functions.join(", ")}</span>
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <pre className="overflow-x-auto rounded bg-zinc-50 p-2 text-[11px] leading-relaxed text-zinc-700 dark:bg-zinc-900/60 dark:text-zinc-300">
      {JSON.stringify({ input, output }, null, 2)}
    </pre>
  );
}

const TOOL_LABEL: Record<string, string> = {
  search_related_regulations: "Searched prior regulations",
  lookup_company_profile: "Looked up company profile",
};

/** Collapsible "Agent reasoning" panel rendered on a reg document detail page.
 * Reads enrichment_full.tool_calls — empty array means the model answered
 * without invoking any tools. */
export function AgentReasoningTrace({ calls }: { calls: ReadonlyArray<RegToolCall> }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const count = calls.length;

  return (
    <section className="surface-card mt-6 p-5 sm:p-6">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center justify-between gap-3 text-left"
        aria-expanded={open}
        aria-controls={panelId}
      >
        <div>
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Agent reasoning</h2>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            {count === 0
              ? "The model answered directly without calling any tools."
              : `${count} tool call${count === 1 ? "" : "s"} during enrichment.`}
          </p>
        </div>
        {count > 0 ? (
          <span className="text-xs font-medium text-teal-700 dark:text-teal-400">{open ? "Hide" : "Show"}</span>
        ) : null}
      </button>

      {count > 0 ? (
        <div id={panelId} role="region" aria-label="Tool calls" hidden={!open} className="mt-4 space-y-4">
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Claude has read-only tools during enrichment: <code className="font-mono text-[11px]">search_related_regulations</code>{" "}
            and <code className="font-mono text-[11px]">lookup_company_profile</code>. Each call below shows what the model asked for and what came back.
          </p>
          <ol className="space-y-3">
            {calls.map((call, i) => (
              <li
                key={i}
                className="rounded-lg border border-zinc-200/80 bg-white/60 px-3 py-2.5 dark:border-zinc-800 dark:bg-zinc-950/30 sm:px-4 sm:py-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-teal-500/15 px-2 py-0.5 font-mono text-[11px] font-medium text-teal-900 dark:text-teal-100">
                    {i + 1}
                  </span>
                  <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                    {TOOL_LABEL[call.name] ?? call.name}
                  </span>
                  <code className="font-mono text-[11px] text-zinc-500 dark:text-zinc-500">{call.name}</code>
                  {call.is_error ? (
                    <span className="rounded bg-red-500/15 px-1.5 py-0.5 font-mono text-[10px] uppercase text-red-800 dark:text-red-200">
                      error
                    </span>
                  ) : null}
                </div>
                <div className="mt-2">
                  <ToolCallBody call={call} />
                </div>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
