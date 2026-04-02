"use client";

import { renderTranscriptParagraph } from "@/components/transcript/transcriptHighlight";
import type { TranscriptSection } from "@/lib/api";
import { formatTranscriptSectionLabel } from "@/lib/transcriptLabels";
import { buildTranscriptBlocks, type TranscriptBlock } from "@/components/transcript/transcriptParagraphs";

const SECTION_HEADINGS: Record<string, string> = {
  operator_intro: "Opening (operator & introductions)",
  prepared_remarks: "Prepared remarks",
  qa: "Q&A session",
};

function topBorderBefore(i: number, blocks: TranscriptBlock[]): boolean {
  if (i === 0) return false;
  const b = blocks[i];
  if (b.kind === "qa-turn") return false;
  if (b.kind === "body" && b.topicDepth === 0) return true;
  return false;
}

export function TranscriptReader({ sections }: { sections: TranscriptSection[] }) {
  if (!sections.length) return null;

  const ordered = [...sections].sort((a, b) => a.order - b.order);

  return (
    <div className="surface-card overflow-hidden">
      <div className="border-b border-zinc-200/90 px-4 py-3 dark:border-zinc-800 sm:px-6">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Transcript</h2>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          One continuous read: sections follow the usual earnings-call structure (opening, management remarks, then{" "}
          {"Q&A"}). Dollar amounts, percentages, and common terms are <strong className="font-medium">bolded</strong>;
          speaker lines are labeled when detected. In {"Q&A"}, blocks are tagged <strong className="font-medium">Q</strong>{" "}
          (audience / handoff) vs <strong className="font-medium">A</strong> (management) using heuristics — not always
          perfect. Elsewhere, topic cues like &quot;Next&quot; or &quot;Let me&quot; start indented sub-paragraphs.
        </p>
      </div>
      <div className="max-h-[min(75vh,880px)] overflow-y-auto px-4 py-5 sm:px-6 sm:py-6">
        {ordered.map((s, idx) => {
          const label = SECTION_HEADINGS[s.section_type] ?? formatTranscriptSectionLabel(s.section_type);
          const blocks = buildTranscriptBlocks(s.section_type, s.text);
          const firstBodyIdx = blocks.findIndex((b) => b.kind === "body");
          return (
            <article
              key={s.id}
              className={
                idx > 0 ? "mt-10 border-t border-zinc-200 pt-10 dark:border-zinc-800" : ""
              }
            >
              <header className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                  {label}
                </h3>
                <span className="font-mono text-xs text-zinc-400">{s.text.length.toLocaleString()} chars</span>
              </header>
              {s.speaker ? (
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                  Primary speaker cue: <span className="font-medium text-zinc-600 dark:text-zinc-300">{s.speaker}</span>
                </p>
              ) : null}
              <div className="mt-4 max-w-[68ch] font-sans text-[15px] leading-[1.7] text-zinc-800 dark:text-zinc-200">
                {blocks.map((b, i) => {
                  const tb = topBorderBefore(i, blocks);
                  if (b.kind === "qa-turn") {
                    const isQ = b.role === "q";
                    return (
                      <p
                        key={`${s.id}-qa-${b.index}`}
                        className={`flex gap-2.5 hyphens-auto whitespace-pre-line rounded-r-lg border border-l-4 border-y border-r border-zinc-200 py-3 pl-4 pr-3 dark:border-zinc-800 ${
                          isQ
                            ? "border-l-amber-500/90 bg-zinc-50/90 dark:border-l-amber-500/70 dark:bg-zinc-900/40"
                            : "border-l-teal-600/70 bg-zinc-50/60 dark:border-l-teal-500/60 dark:bg-zinc-900/25"
                        } ${i > 0 ? "mt-4" : ""}`}
                      >
                        <strong
                          className={`shrink-0 select-none pt-0.5 text-lg font-bold leading-none ${
                            isQ
                              ? "text-amber-700 dark:text-amber-300"
                              : "text-teal-800 dark:text-teal-300"
                          }`}
                          aria-label={isQ ? "Question" : "Answer"}
                        >
                          {isQ ? "Q" : "A"}
                        </strong>
                        <span className="min-w-0 flex-1">{renderTranscriptParagraph(b.text)}</span>
                      </p>
                    );
                  }
                  const isFirstBody = b.kind === "body" && i === firstBodyIdx;
                  return (
                    <p
                      key={`${s.id}-b-${i}`}
                      className={`hyphens-auto whitespace-pre-line ${
                        b.topicDepth === 1
                          ? "ml-1 border-l-2 border-zinc-300 pl-4 indent-0 dark:border-zinc-600"
                          : isFirstBody
                            ? "indent-0"
                            : "indent-8"
                      } ${tb ? "mt-5 border-t border-zinc-100 pt-5 dark:border-zinc-800/60" : ""} ${
                        b.topicDepth === 1 ? "mt-3" : ""
                      }`}
                    >
                      {renderTranscriptParagraph(b.text)}
                    </p>
                  );
                })}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
