"use client";

import { Suspense } from "react";

import { AskWorkspace } from "@/components/ask/AskWorkspace";
import { AskHomeFromUrl } from "@/components/home/AskHomeFromUrl";
import { RecentActivity } from "@/components/home/RecentActivity";
import { PageHeader, PageShell } from "@/components/PageShell";

export default function HomePage() {
  return (
    <PageShell width="wide" mainClassName="relative flex flex-col lg:min-h-[calc(100dvh-4.5rem)]">
      <div
        className="pointer-events-none absolute inset-x-4 top-0 h-48 bg-gradient-to-b from-teal-500/12 via-transparent to-transparent sm:inset-x-6 lg:inset-x-8 dark:from-teal-400/8"
        aria-hidden
      />

      <PageHeader
        eyebrow="Stock Intelligence"
        title="Ask about earnings & regulations"
        description="Type a question in plain English. The orchestrator researches Federal Register rules and earnings call narrative for your company. Watch each step on the right."
        className="relative shrink-0"
      />

      <div className="relative mt-6 flex min-h-0 flex-1 flex-col lg:mt-8">
        <Suspense fallback={<AskWorkspace />}>
          <AskHomeFromUrl />
        </Suspense>
      </div>

      <RecentActivity />
    </PageShell>
  );
}
