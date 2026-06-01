"use client";

import { Suspense } from "react";

import { AskWorkspace } from "@/components/ask/AskWorkspace";
import { AskHomeFromUrl } from "@/components/home/AskHomeFromUrl";
import { RecentActivity } from "@/components/home/RecentActivity";

export default function HomePage() {
  return (
    <div className="page-canvas relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <div
        className="pointer-events-none absolute inset-x-0 top-14 h-48 bg-gradient-to-b from-teal-500/12 via-transparent to-transparent dark:from-teal-400/8"
        aria-hidden
      />
      <main className="relative mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-xs font-medium uppercase tracking-widest text-teal-700 dark:text-teal-400/90">
            Stock Intelligence
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl">
            Ask about earnings &amp; regulations
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Type a question in plain English. The orchestrator researches Federal Register rules and earnings
            call narrative for your company. Watch each step on the right.
          </p>
        </div>

        <div className="mt-8">
          <Suspense fallback={<AskWorkspace />}>
            <AskHomeFromUrl />
          </Suspense>
        </div>

        <RecentActivity />
      </main>
    </div>
  );
}
