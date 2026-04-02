/** Human-readable labels for transcript / sentiment section keys (API uses snake_case). */
const SECTION_LABELS: Record<string, string> = {
  operator_intro: "Operator intro",
  prepared_remarks: "Prepared remarks",
  qa: "Q&A",
};

export function formatTranscriptSectionLabel(section: string): string {
  const k = section.trim().toLowerCase().replace(/\s+/g, "_");
  if (SECTION_LABELS[k]) return SECTION_LABELS[k];
  return k
    .split("_")
    .filter(Boolean)
    .map((part) => (part === "qa" ? "Q&A" : part.replace(/^\w/, (c) => c.toUpperCase())))
    .join(" ");
}
