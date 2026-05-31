"use client";

import { useSearchParams } from "next/navigation";

import { AskWorkspace } from "@/components/ask/AskWorkspace";
import { parseAskSearchParams } from "@/lib/ask";

export function AskHomeFromUrl() {
  const searchParams = useSearchParams();
  const { context, initialQuestion, autoRun } = parseAskSearchParams(searchParams);

  return (
    <AskWorkspace
      context={Object.keys(context).length ? context : undefined}
      initialQuestion={initialQuestion}
      autoRun={autoRun}
      showExamples={!context.ticker && !context.regulation_id}
    />
  );
}
