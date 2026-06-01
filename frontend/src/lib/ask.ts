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

export const ASK_TOOLS_BY_AGENT: Record<"regulations" | "earnings", readonly string[]> = {
  regulations: [
    "lookup_company_profile",
    "search_related_regulations",
    "search_regulations",
    "impact_by_ticker",
    "list_regulations",
    "get_regulation",
  ],
  earnings: [
    "list_transcripts_for_ticker",
    "get_transcript_analysis",
    "search_transcript_quotes",
    "search_transcripts",
    "company_earnings_timeline",
  ],
};

export const ASK_TOOL_LABELS: Record<string, string> = {
  lookup_company_profile: "Looked up company profile",
  search_related_regulations: "Searched related regulations",
  search_regulations: "Searched regulations (filtered)",
  impact_by_ticker: "Matched rules to company profile",
  list_regulations: "Searched regulation catalog",
  get_regulation: "Opened regulation document",
  list_transcripts_for_ticker: "Listed earnings transcripts",
  get_transcript_analysis: "Loaded call analysis",
  search_transcript_quotes: "Searched call quotes",
  search_transcripts: "Searched transcript text",
  company_earnings_timeline: "Reviewed earnings timeline",
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

export function defaultCompanyAskQuestion(ticker: string): string {
  const t = ticker.trim().toUpperCase();
  return `What recent regulations might affect ${t}, and why?`;
}

export function defaultRegulationAskQuestion(documentNumber?: string): string {
  if (documentNumber?.trim()) {
    return `Who might Federal Register document ${documentNumber.trim()} affect, and what are the main compliance themes?`;
  }
  return "Who might this Federal Register rule affect, and what are the main compliance themes?";
}

/** Build home URL with Ask context query params. */
export function buildAskHref(params: {
  ticker?: string;
  regulation_id?: string;
  q?: string;
  auto?: boolean;
}): string {
  const sp = new URLSearchParams();
  if (params.ticker?.trim()) sp.set("ticker", params.ticker.trim().toUpperCase());
  if (params.regulation_id?.trim()) sp.set("regulation_id", params.regulation_id.trim());
  if (params.q?.trim()) sp.set("q", params.q.trim());
  if (params.auto) sp.set("auto", "1");
  const qs = sp.toString();
  return qs ? `/?${qs}` : "/";
}

export function parseAskSearchParams(searchParams: URLSearchParams): {
  context: AskContext;
  initialQuestion: string;
  autoRun: boolean;
} {
  const ticker = searchParams.get("ticker")?.trim().toUpperCase() || undefined;
  const regulation_id = searchParams.get("regulation_id")?.trim() || undefined;
  const q = searchParams.get("q")?.trim() || "";
  const context: AskContext = {};
  if (ticker) context.ticker = ticker;
  if (regulation_id) context.regulation_id = regulation_id;
  return {
    context,
    initialQuestion: q,
    autoRun: searchParams.get("auto") === "1",
  };
}
