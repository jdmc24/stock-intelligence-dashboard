import type { ReactNode } from "react";

/**
 * Highlights figures and recurring earnings-call vocabulary. Uses a single
 * capturing regex so split() alternates plain / match segments.
 * Longer phrases are listed first so alternation prefers them.
 */
const HIGHLIGHT_SOURCE = [
  String.raw`\$[\d,.]+(?:\s*(?:billion|million|trillion|B|M|T|bn|mm)\b)?`,
  String.raw`\b\d+(?:\.\d+)?%`,
  String.raw`year[-\s]over[-\s]year`,
  String.raw`free\s+cash\s+flow`,
  String.raw`earnings\s+per\s+share`,
  String.raw`net\s+interest\s+(?:income|margin|expense)`,
  String.raw`operating\s+margin`,
  String.raw`gross\s+margin`,
  String.raw`adjusted\s+EBITDA`,
  String.raw`constant\s+currency`,
  String.raw`organic\s+growth`,
  String.raw`share\s+repurchase`,
  String.raw`forward[-\s]looking`,
  String.raw`net\s+income`,
  String.raw`\bEBITDA\b`,
  String.raw`\bEBIT\b`,
  String.raw`\bEPS\b`,
  String.raw`\bYoY\b`,
  String.raw`\bY\/Y\b`,
  String.raw`\bmacroeconomic\b`,
  String.raw`\bsequential\b`,
  String.raw`\brepurchases?\b`,
  String.raw`\bheadwinds?\b`,
  String.raw`\btailwinds?\b`,
  String.raw`\bguidance\b`,
  String.raw`\boutlook\b`,
  String.raw`\brevenue\b`,
  String.raw`\bdividend\b`,
  String.raw`\bcapex\b`,
  String.raw`\bliquidity\b`,
  String.raw`\bleverage\b`,
  String.raw`\bbuyback\b`,
  String.raw`\bmargins?\b`,
  String.raw`\bQ[1-4]\b`,
  String.raw`\bFY\d{2,4}\b`,
].join("|");

const HIGHLIGHT_RE = new RegExp(`(${HIGHLIGHT_SOURCE})`, "gi");

export function highlightTranscriptText(text: string): ReactNode {
  const parts = text.split(HIGHLIGHT_RE);
  return (
    <>
      {parts.map((part, i) =>
        !part ? null : i % 2 === 1 ? (
          <strong
            key={i}
            className="font-semibold text-zinc-950 dark:text-zinc-50"
          >
            {part}
          </strong>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

const SPEAKER_PREFIX = /^([A-Z][A-Za-z.'\-\s]{2,80}:\s*)(?:\r?\n)?([\s\S]*)$/;

/** Optional leading "Name:" line gets a stronger label; body is highlighted. */
export function renderTranscriptParagraph(para: string): ReactNode {
  const m = para.match(SPEAKER_PREFIX);
  if (m) {
    const [, prefix, body] = m;
    return (
      <>
        <span className="font-semibold text-zinc-900 dark:text-zinc-100">{prefix}</span>
        {body.trimStart() ? (
          <>
            {"\n"}
            {highlightTranscriptText(body.trimStart())}
          </>
        ) : null}
      </>
    );
  }
  return highlightTranscriptText(para);
}
