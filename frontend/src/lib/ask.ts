import { API_BASE, authHeaders } from "@/lib/api";

export type AskEventType =
  | "run_started"
  | "plan"
  | "agent_start"
  | "agent_end"
  | "tool_start"
  | "tool_end"
  | "message"
  | "answer_delta"
  | "answer"
  | "run_end"
  | "error"
  | "ping";

export type AskEvent = {
  run_id: string;
  seq: number;
  ts: string;
  type: AskEventType;
  [key: string]: unknown;
};

export type AskCitation = {
  kind: "regulation" | "company_profile" | "transcript" | "analysis";
  id: string;
  label: string;
  href: string;
};

export type AskContext = {
  ticker?: string;
  regulation_id?: string;
  lookback_days?: number;
};

export const ASK_TOOL_LABELS: Record<string, string> = {
  lookup_company_profile: "Looked up company profile",
  search_related_regulations: "Searched related regulations",
  impact_by_ticker: "Matched rules to company profile",
  list_regulations: "Searched regulation catalog",
};

export const ASK_AGENT_LABELS: Record<string, string> = {
  orchestrator: "Orchestrator",
  regulations: "Regulations specialist",
  earnings: "Earnings specialist",
  synthesizer: "Synthesizer",
};

function parseSseBlock(block: string): AskEvent | null {
  const lines = block.split("\n");
  let dataLine = "";
  for (const line of lines) {
    if (line.startsWith("data:")) {
      dataLine += line.slice(5).trim();
    }
  }
  if (!dataLine) return null;
  try {
    return JSON.parse(dataLine) as AskEvent;
  } catch {
    return null;
  }
}

/** POST /api/ask/stream and invoke onEvent for each SSE frame. */
export async function streamAsk(
  question: string,
  context: AskContext | undefined,
  onEvent: (event: AskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${API_BASE}/api/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ question, context: context ?? null }),
    cache: "no-store",
    signal,
  });
  if (!r.ok) {
    throw new Error(await r.text());
  }
  if (!r.body) {
    throw new Error("No response body");
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const ev = parseSseBlock(part);
      if (ev) onEvent(ev);
    }
  }
  if (buffer.trim()) {
    const ev = parseSseBlock(buffer);
    if (ev) onEvent(ev);
  }
}
