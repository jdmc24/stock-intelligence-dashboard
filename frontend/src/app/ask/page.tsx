"use client";

import Link from "next/link";
import { useCallback, useRef, useState } from "react";

import {
  AskCitationList,
  OrchestratorTracePanel,
} from "@/components/ask/OrchestratorTracePanel";
import { streamAsk, type AskCitation, type AskEvent } from "@/lib/ask";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: AskCitation[];
  limitations?: string[];
};

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<AskEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const onSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = question.trim();
      if (!q || running) return;

      setError(null);
      setRunning(true);
      setEvents([]);
      setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", text: q }]);
      setQuestion("");

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await streamAsk(
          q,
          undefined,
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
    [question, running],
  );

  return (
    <div className="page-canvas flex min-h-0 flex-1 flex-col">
      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 py-8 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
            Ask
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-3xl">
            Cross-domain research
          </h1>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
            Ask about regulations and companies. Phase 1 covers Federal Register research; earnings call
            analysis plugs in on the right-hand trace without changing this chat.
          </p>
        </div>

        <div className="mt-8 grid min-h-0 flex-1 gap-6 lg:grid-cols-2 lg:gap-8">
          <section className="flex min-h-[480px] flex-col rounded-xl border border-zinc-200/90 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/30">
            <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
              {messages.length === 0 ? (
                <p className="text-sm text-zinc-500">
                  Try: &ldquo;What recent SEC rules might affect how MSFT discusses AI?&rdquo;
                </p>
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
                    <div className="whitespace-pre-wrap">{m.text}</div>
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
              {error ? (
                <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
              ) : null}
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
                placeholder="Ask a question…"
                disabled={running}
                className="w-full resize-none rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
              <div className="mt-3 flex items-center justify-between gap-2">
                <Link href="/regulations" className="text-xs text-zinc-500 hover:text-teal-600 dark:hover:text-teal-400">
                  Browse regulations →
                </Link>
                <button
                  type="submit"
                  disabled={running || !question.trim()}
                  className="btn-primary text-sm disabled:opacity-50"
                >
                  {running ? "Thinking…" : "Ask"}
                </button>
              </div>
            </form>
          </section>

          <OrchestratorTracePanel events={events} running={running} />
        </div>
      </main>
    </div>
  );
}
