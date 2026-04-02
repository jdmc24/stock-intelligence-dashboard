export type TranscriptSection = {
  id: string;
  transcript_id: string;
  section_type: "operator_intro" | "prepared_remarks" | "qa";
  speaker: string | null;
  text: string;
  order: number;
};

export type Transcript = {
  id: string;
  ticker: string;
  company_name: string | null;
  quarter: string | null;
  call_date: string | null;
  source: "earningscall" | "upload";
  source_url: string | null;
  raw_text: string;
  status: "raw" | "processing" | "analyzed" | "error";
  error_message: string | null;
  created_at: string;
  processed_at: string | null;
  sections: TranscriptSection[];
};

/** Set in `.env.local` as NEXT_PUBLIC_BACKEND_URL (must match your uvicorn port). Restart `npm run dev` after changing. */
export const API_BASE =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.NEXT_PUBLIC_API_BEARER_TOKEN ?? "";

function authHeaders(): HeadersInit {
  return TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
}

export async function fetchTranscript(ticker: string, quarter?: string) {
  const r = await fetch(`${API_BASE}/api/earnings/transcripts/fetch`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ ticker, quarter: quarter || null }),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as { transcript_id: string; status: Transcript["status"] };
}

export async function uploadTranscript(args: {
  ticker: string;
  quarter?: string;
  company_name?: string;
  call_date?: string;
  raw_text: string;
}) {
  const r = await fetch(`${API_BASE}/api/earnings/transcripts/upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      ticker: args.ticker,
      quarter: args.quarter ?? null,
      company_name: args.company_name ?? null,
      call_date: args.call_date ?? null,
      raw_text: args.raw_text,
    }),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as { transcript_id: string; status: Transcript["status"] };
}

export async function getTranscript(id: string) {
  const r = await fetch(`${API_BASE}/api/earnings/transcripts/${id}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as Transcript;
}

export async function listTranscripts(params?: {
  ticker?: string;
  status?: string;
  limit?: number;
}) {
  const sp = new URLSearchParams();
  if (params?.ticker?.trim()) sp.set("ticker", params.ticker.trim());
  if (params?.status?.trim()) sp.set("status", params.status.trim());
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString();
  const r = await fetch(`${API_BASE}/api/earnings/transcripts${qs ? `?${qs}` : ""}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as Transcript[];
}

export type Analysis = {
  transcript_id: string;
  status: "processing" | "complete" | "error";
  error_message: string | null;
  summary: string | null;
  sentiment: Record<string, unknown> | null;
  hedging: Record<string, unknown> | null;
  guidance: Record<string, unknown> | null;
  topics: Record<string, unknown> | null;
  model_used: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export async function getAnalysis(transcriptId: string, rerun?: boolean) {
  const q = rerun ? "?rerun=true" : "";
  const r = await fetch(`${API_BASE}/api/earnings/analysis/${transcriptId}${q}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as Analysis;
}

export type ComparisonResponse = {
  model_used: string;
  comparison: Record<string, unknown>;
};

export async function compareAnalyses(body: {
  transcript_ids: string[];
  dimensions?: string[];
}) {
  const r = await fetch(`${API_BASE}/api/earnings/analysis/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as ComparisonResponse;
}

export type CompanySummary = {
  ticker: string;
  company_name: string | null;
  transcript_count: number;
};

export async function listCompanies() {
  const r = await fetch(`${API_BASE}/api/earnings/companies`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CompanySummary[];
}

export type TimelinePoint = {
  transcript_id: string;
  quarter: string | null;
  call_date: string | null;
  overall_tone: string | null;
  hedging_score: number | null;
  guidance_count: number;
  top_topics: string[];
};

export type CompanyTimeline = {
  ticker: string;
  company_name: string | null;
  points: TimelinePoint[];
};

export async function getCompanyTimeline(ticker: string) {
  const t = encodeURIComponent(ticker.trim());
  const r = await fetch(`${API_BASE}/api/earnings/companies/${t}/timeline`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CompanyTimeline;
}

export type SearchHit = {
  transcript_id: string;
  ticker: string;
  quarter: string | null;
  company_name: string | null;
  status: Transcript["status"];
  snippet: string;
};

export type QuoteHit = {
  transcript_id: string;
  ticker: string;
  quarter: string | null;
  section_type: TranscriptSection["section_type"];
  speaker: string | null;
  excerpt: string;
  order: number;
};

export async function searchTranscripts(params: { company?: string; topic?: string; q?: string }) {
  const sp = new URLSearchParams();
  if (params.company?.trim()) sp.set("company", params.company.trim());
  if (params.topic?.trim()) sp.set("topic", params.topic.trim());
  if (params.q?.trim()) sp.set("q", params.q.trim());
  const qs = sp.toString();
  const r = await fetch(`${API_BASE}/api/earnings/search${qs ? `?${qs}` : ""}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as SearchHit[];
}

// ——— Regulatory Change Monitor ———

export type RegEnrichmentSummary = {
  summary: string;
  change_type: string;
  effective_date: string | null;
  severity: string;
  affected_products: string[];
  affected_functions: string[];
};

export type RegDocumentListItem = {
  id: string;
  document_number: string;
  title: string;
  abstract: string | null;
  publication_date: string;
  document_type: string;
  agencies: string[];
  federal_register_url: string;
  pdf_url: string | null;
  cfr_references: string[];
  topics: string[];
  status: string;
  enrichment: RegEnrichmentSummary | null;
  created_at: string | null;
  updated_at: string | null;
};

export type RegProvision = {
  title: string;
  description: string;
  cfr_reference: string | null;
};

export type RegDocumentDetail = RegDocumentListItem & {
  raw_text: string;
  enrichment_full?: {
    summary: string;
    change_type: string;
    effective_date: string | null;
    comment_deadline: string | null;
    compliance_deadline: string | null;
    is_final: boolean | null;
    severity: string;
    severity_rationale: string | null;
    affected_products: string[];
    affected_functions: string[];
    institution_types: string[];
    provisions: RegProvision[];
    model_used: string;
    prompt_version: string;
  };
};

export async function listRegulatoryDocuments(params?: {
  page?: number;
  per_page?: number;
  agency?: string;
  type?: string;
  search?: string;
}) {
  const sp = new URLSearchParams();
  if (params?.page != null) sp.set("page", String(params.page));
  if (params?.per_page != null) sp.set("per_page", String(params.per_page));
  if (params?.agency?.trim()) sp.set("agency", params.agency.trim());
  if (params?.type?.trim()) sp.set("type", params.type.trim());
  if (params?.search?.trim()) sp.set("search", params.search.trim());
  const qs = sp.toString();
  const r = await fetch(`${API_BASE}/api/regulations/documents${qs ? `?${qs}` : ""}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as {
    items: RegDocumentListItem[];
    total: number;
    page: number;
    per_page: number;
  };
}

export async function getRegulatoryDocument(id: string) {
  const r = await fetch(`${API_BASE}/api/regulations/documents/${encodeURIComponent(id)}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as RegDocumentDetail;
}

export type RegulatoryPipelineStatus = {
  reg_documents_count: number;
  enriched_count: number;
  raw_pending_count: number;
  processing_count: number;
  error_count: number;
  last_document_ingested_at: string | null;
  last_enrichment_at: string | null;
  company_profiles_count: number;
  anthropic_configured: boolean;
  enrichment_coverage_percent: number | null;
  enrichment_pipeline_ok: boolean;
  ticker_matching_ready: boolean;
  warnings: string[];
  message?: string;
};

export async function getRegulatoryStatus() {
  const r = await fetch(`${API_BASE}/api/regulations/status`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as RegulatoryPipelineStatus;
}

export async function triggerRegulatoryIngest(days: number = 3) {
  const r = await fetch(
    `${API_BASE}/api/regulations/ingest/trigger?days=${encodeURIComponent(String(days))}`,
    {
      method: "POST",
      headers: { ...authHeaders() },
      cache: "no-store",
    },
  );
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as Record<string, unknown>;
}

export async function triggerRegulatoryEnrich(limit: number = 5) {
  const r = await fetch(
    `${API_BASE}/api/regulations/enrich/trigger?limit=${encodeURIComponent(String(limit))}`,
    {
      method: "POST",
      headers: { ...authHeaders() },
      cache: "no-store",
    },
  );
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as Record<string, unknown>;
}

export type CompanyRegProfile = {
  ticker: string;
  name: string;
  institution_types: string[];
  primary_products: string[];
  primary_functions: string[];
  gics_sector: string | null;
  gics_sub_industry: string | null;
  is_auto_generated: boolean;
};

export async function getCompanyRegProfile(ticker: string) {
  const t = encodeURIComponent(ticker.trim().toUpperCase());
  const r = await fetch(`${API_BASE}/api/companies/${t}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CompanyRegProfile;
}

export async function listCompanyRegProfiles() {
  const r = await fetch(`${API_BASE}/api/companies`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CompanyRegProfile[];
}

/** Body for PUT /api/companies/{ticker} — full create or replace. */
export type CompanyRegProfilePut = {
  name: string;
  institution_types: string[];
  primary_products: string[];
  primary_functions: string[];
  gics_sector?: string | null;
  gics_sub_industry?: string | null;
  is_auto_generated?: boolean;
};

export type CompanyRegProfilePatch = Partial<CompanyRegProfilePut>;

export async function putCompanyRegProfile(ticker: string, body: CompanyRegProfilePut) {
  const t = encodeURIComponent(ticker.trim().toUpperCase());
  const r = await fetch(`${API_BASE}/api/companies/${t}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CompanyRegProfile;
}

export async function patchCompanyRegProfile(ticker: string, body: CompanyRegProfilePatch) {
  const t = encodeURIComponent(ticker.trim().toUpperCase());
  const r = await fetch(`${API_BASE}/api/companies/${t}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CompanyRegProfile;
}

export async function deleteCompanyRegProfile(ticker: string) {
  const t = encodeURIComponent(ticker.trim().toUpperCase());
  const r = await fetch(`${API_BASE}/api/companies/${t}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (r.status === 404) throw new Error("Company profile not found");
  if (!r.ok) throw new Error(await r.text());
}

export type RegulatoryImpactResponse = {
  ticker: string;
  company_name: string;
  lookback_days: number;
  profile_products: string[];
  profile_functions: string[];
  matches: RegDocumentListItem[];
  note: string | null;
};

export async function getRegulatoryImpactByTicker(ticker: string, lookbackDays: number = 90) {
  const t = encodeURIComponent(ticker.trim().toUpperCase());
  const r = await fetch(
    `${API_BASE}/api/regulations/impact/by-ticker/${t}?lookback_days=${encodeURIComponent(String(lookbackDays))}`,
    {
      headers: { ...authHeaders() },
      cache: "no-store",
    },
  );
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as RegulatoryImpactResponse;
}

export type RegulatoryImpactBatchResponse = {
  lookback_days: number;
  by_ticker: Record<string, RegulatoryImpactResponse | null>;
};

/** One request for many tickers; `by_ticker[T]` is null when there is no company profile (same as single-ticker 404). */
export async function getRegulatoryImpactBatch(
  tickers: string[],
  lookbackDays: number = 90,
): Promise<RegulatoryImpactBatchResponse> {
  const uniq = [...new Set(tickers.map((t) => t.trim().toUpperCase()).filter(Boolean))];
  if (uniq.length === 0) {
    return { lookback_days: lookbackDays, by_ticker: {} };
  }
  const r = await fetch(`${API_BASE}/api/regulations/impact/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ tickers: uniq, lookback_days: lookbackDays }),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as RegulatoryImpactBatchResponse;
}

export async function searchQuotes(query: string, company?: string) {
  const sp = new URLSearchParams();
  sp.set("query", query.trim());
  if (company?.trim()) sp.set("company", company.trim());
  const r = await fetch(`${API_BASE}/api/earnings/search/quotes?${sp.toString()}`, {
    headers: { ...authHeaders() },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as QuoteHit[];
}

