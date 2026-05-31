"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  AskCitationList,
  OrchestratorTracePanel,
} from "@/components/ask/OrchestratorTracePanel";
import { AskAnswerMarkdown } from "@/components/ask/AskAnswerMarkdown";
import { AskRunProgress } from "@/components/ask/AskRunProgress";
import {
  streamAsk,
  type AskCitation,
  type AskContext,
  type AskEvent,
} from "@/lib/ask";

export const ASK_EXAMPLE_PROMPTS = [
  "What recent SEC rules might affect how MSFT discusses AI?",
  "Which Federal Register items overlap JPM's cybersecurity profile?",
  "Summarize high-severity banking regulations from the last 90 days.",
] as const;

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: AskCitation[];
  limitations?: string[];
};

type AskWorkspaceProps = {
  initialQuestion?: string;
  context?: AskContext;
  showExamples?: boolean;
  autoRun?: boolean;
};

function ContextBanner({ context }: { context: AskContext }) {
  const parts: string[] = [];
  if (context.ticker) parts.push(`Company: ${context.ticker}`);
  if (context.regulation_id) parts.push(`Regulation id: ${context.regulation_id.slice(0, 8)}…`);
  if (!parts.length) return null;
  return (
    <div className="mb-4 rounded-lg border border-teal-500/25 bg-teal-500/10 px-3 py-2 text-xs text-teal-900 dark:text-teal-100">
      <span className="font-medium">Context: </span>
      {parts.join(" · ")}
      <Link href="/" className="ml-2 text-teal-700 underline dark:text-teal-300">
        Clear
      </Link>
    </div>
  );
}

export function AskWorkspace({
  initialQuestion = "",
  context,
  showExamples = true,
  autoRun = false,
}: AskWorkspaceProps) {
  const [question, setQuestion] = useState(initialQuestion);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<AskEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const autoRanRef = useRef(false);

  useEffect(() => {
    setQuestion(initialQuestion);
    autoRanRef.current = false;
  }, [initialQuestion, context?.ticker, context?.regulation_id]);

  const runQuestion = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed || running) return;

      setError(null);
      setRunning(true);
      setEvents([]);
      setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", text: trimmed }]);
      setQuestion("");

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await streamAsk(
          trimmed,
          context,
          (ev) => {
            setEvents((prev) => [...prev, ev]);
            if (ev.type === "answer") {
              const citations = (ev.citations as AskCitation[] | undefined) ?? [];
              const limitations = (ev.limitations as string[] | undefined) ?? [];
              setMessages((prev) => [
                ...prev,
                {
                  id: `a-${ev.run_id}-${ev.seq}`,
                  role: "assistant",
                  text: String(ev.markdown ?? ""),
                  citations,
                  limitations,
                },
              ]);
            }
            if (ev.type === "error") {
              setError(String(ev.message ?? "Something went wrong"));
            }
          },
          controller.signal,
        );
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError(err instanceof Error ? err.message : "Request failed");
        }
      } finally {
        setRunning(false);
        abortRef.current = null;
      }
    },
    [running, context],
  );

  useEffect(() => {
    if (!autoRun || autoRanRef.current || !initialQuestion.trim()) return;
    autoRanRef.current = true;
    void runQuestion(initialQuestion);
  }, [autoRun, initialQuestion, runQuestion]);

  const onSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      await runQuestion(question);
    },
    [question, runQuestion],
  );

  const hideExamples = !showExamples || Boolean(context?.ticker || context?.regulation_id);

  return (
    <div className="grid min-h-[min(72vh,640px)] gap-6 lg:grid-cols-2 lg:gap-8">
      <section className="flex min-h-[420px] flex-col rounded-xl border border-zinc-200/90 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/30">
        {context && (context.ticker || context.regulation_id) ? (
          <div className="border-b border-zinc-200/80 px-4 pt-4 dark:border-zinc-800">
            <ContextBanner context={context} />
          </div>
        ) : null}
        <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
          {messages.length === 0 && !hideExamples ? (
            <div className="space-y-3">
              <p className="text-sm text-zinc-500">Try an example:</p>
              <div className="flex flex-col gap-2">
                {ASK_EXAMPLE_PROMPTS.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    disabled={running}
                    onClick={() => runQuestion(ex)}
                    className="rounded-xl border border-zinc-200/90 px-3 py-2.5 text-left text-sm text-zinc-700 transition hover:border-teal-500/40 hover:bg-teal-50/50 disabled:opacity-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:border-teal-500/30 dark:hover:bg-teal-950/20"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {messages.map((m) => (
            <div
              key={m.id}
              className={`max-w-[95%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                m.role === "user"
                  ? "ml-auto bg-teal-600 text-white"
                  : "bg-zinc-100 text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200"
              }`}
            >
              {m.role === "assistant" ? (
                <AskAnswerMarkdown content={m.text} />
              ) : (
                m.text
              )}
              {m.citations?.length ? <AskCitationList citations={m.citations} /> : null}
              {m.limitations?.length ? (
                <ul className="mt-3 space-y-1 border-t border-zinc-300/50 pt-2 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
                  {m.limitations.map((lim) => (
                    <li key={lim}>• {lim}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
          {running ? <AskRunProgress events={events} running={running} /> : null}
          {error ? <p className="text-sm text-red-700 dark:text-red-300">{error}</p> : null}
        </div>

        <form onSubmit={onSubmit} className="border-t border-zinc-200/80 p-4 dark:border-zinc-800">
          <label htmlFor="ask-input" className="sr-only">
            Your question
          </label>
          <textarea
            id="ask-input"
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about a company, a rule, or a theme…"
            disabled={running}
            className="w-full resize-none rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
          <div className="mt-3 flex items-center justify-between gap-2">
            <Link href="/regulations" className="text-xs text-zinc-500 hover:text-teal-600 dark:hover:text-teal-400">
              Browse regulations →
            </Link>
            <button type="submit" disabled={running || !question.trim()} className="btn-primary text-sm disabled:opacity-50">
              {running ? "Thinking…" : "Ask"}
            </button>
          </div>
        </form>
      </section>

      <OrchestratorTracePanel events={events} running={running} />
    </div>
  );
}
