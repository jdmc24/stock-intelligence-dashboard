export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  const s = (severity || "unknown").toLowerCase();
  const map: Record<string, string> = {
    critical: "bg-red-500/20 text-red-800 border-red-500/40 dark:text-red-200",
    high: "bg-amber-500/20 text-amber-900 border-amber-500/40 dark:text-amber-200",
    medium: "bg-yellow-500/15 text-yellow-900 border-yellow-500/30 dark:text-yellow-100",
    low: "bg-zinc-500/15 text-zinc-700 border-zinc-500/25 dark:text-zinc-300",
  };
  const cls = map[s] ?? "bg-zinc-500/15 text-zinc-700 border-zinc-500/25 dark:text-zinc-300";
  return (
    <span className={`rounded-md border px-2 py-0.5 text-xs font-medium capitalize ${cls}`}>{s}</span>
  );
}
