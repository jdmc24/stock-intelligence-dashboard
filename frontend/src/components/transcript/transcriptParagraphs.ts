/** Speaker-style line: "Jamie Dimon: Thanks..." */
const SPEAKER_LINE_RE = /^[A-Z][A-Za-z.'\-\s]{2,80}:\s*.+/;

/** "Michael Benetti - RBC Capital Markets" (common in Q&A, no colon) */
const QA_NAME_FIRM_LINE_RE = /^[A-Z][A-Za-z.'\-\s]{2,45}\s+-\s+[A-Z].+/;

/** Operator / host labels */
const QA_ROLE_LINE_RE = /^(?:Operator|Analyst|Moderator|Host|Coordinator|Speaker)\b/i;

function isQASpeakerOrHandoffLine(trimmed: string): boolean {
  if (!trimmed) return false;
  if (SPEAKER_LINE_RE.test(trimmed)) return true;
  if (QA_NAME_FIRM_LINE_RE.test(trimmed)) return true;
  if (QA_ROLE_LINE_RE.test(trimmed)) return true;
  return false;
}

/**
 * Same speaker starts a new sub-topic (common in prepared remarks).
 * Line must start with one of these phrases (after trim).
 */
const TOPIC_LINE_RE =
  /^(?:Now|Next|Moving|Turning|Finally|First|Second|Third|Additionally|In addition|On the margin|Turning to|With respect to|Regarding|As for|Let me|I'd like to|Before I|I would like to|From (?:a )?margin|At (?:a )?high level|Importantly|Specifically|Separately|Looking ahead|To summarize|In summary|With that)\b/i;

/**
 * EarningsCall / vendor transcripts often ship as one long line or few breaks.
 * Insert structural newlines so downstream splitters can see speaker turns.
 */
export function preprocessTranscript(raw: string): string {
  let s = raw.replace(/\r\n/g, "\n").trim();
  if (!s) return s;

  // Moderator / Q&A handoffs (avoid duplicating if already on its own line)
  const moderatorPhrases: RegExp[] = [
    /\bYour next question comes from\b/gi,
    /\bThe next question comes from\b/gi,
    /\bYour next question is from\b/gi,
    /\bWe(?:'| )ll now take your questions\b/gi,
    /\bWe will now take questions\b/gi,
    /\bQuestion-and-answer session\b/gi,
    /\bQuestion and answer session\b/gi,
  ];
  for (const re of moderatorPhrases) {
    s = s.replace(re, "\n\n$&");
  }

  // Sentence end then speaker label "Name: "
  s = s.replace(/([.!?])\s+([A-Z][A-Za-z.'\-\s]{2,80}:\s)/g, "$1\n\n$2");

  // Typical exec name pattern "Jane Smith: " (two capitalized words) after other text
  s = s.replace(/([^\n])\s+([A-Z][a-z]+ [A-Z][a-z]+:\s)/g, "$1\n\n$2");

  // Fallback: space before speaker-style label when not already after newline (long monoliths)
  s = s.replace(/([^\n])\s+([A-Z][A-Za-z.'\-\s]{2,80}:\s)/g, "$1\n\n$2");

  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

/**
 * Extra breaks for Q&A: handoffs, question boundaries, name–firm intros.
 */
function preprocessQASection(raw: string): string {
  let s = raw.replace(/\r\n/g, "\n").trim();
  if (!s) return s;

  // Avoid `\bfrom the line of\b` here — it splits inside "comes from the line of …".
  // Avoid `\bGo ahead,?\s+` — it splits inside "Please go ahead".
  // Do not use bare `\bFirst question\b` — it matches inside management's "On your first question…".
  const handoffs: RegExp[] = [
    /\bPlease go ahead\b/gi,
    /\bOur next question\b/gi,
    /\bThe next question\b/gi,
    // Avoid matching inside "on your follow-up question…" (same speaker).
    /(?<!\b(?:your|my|his|her|their)\s)\bfollow[- ]?up question\b/gi,
    /\bfrom the floor\b/gi,
    /\bI'll turn it (?:over|back)\b/gi,
    /\bturn it over to\b/gi,
    /\bopen (?:the line|it up) for questions\b/gi,
  ];
  for (const re of handoffs) {
    s = s.replace(re, "\n\n$&");
  }

  // Sentence end → "Name - Firm" intro line
  s = s.replace(
    /([.!?])\s+([A-Z][A-Za-z.'\-\s]{2,40}\s+-\s+[A-Z][^\n]{2,100})/g,
    "$1\n\n$2",
  );

  // Question ends, next utterance starts with a capitalized word (answer / new speaker)
  s = s.replace(/(?<=\?)\s{1,}(?=[A-Z][a-z]{2,20}\b)/g, "\n\n");

  // After "thank you" only split when the next sentence is likely a new speaker / handoff,
  // not the same exec continuing (e.g. "Thank you. On your first question…").
  s = s.replace(
    /(thank you[.!]?)\s{1,}(?=[A-Z][a-z]+)(?!On (?:your|the|my)\s)(?!With (?:respect|that)\b)(?!As I\b)(?!Let me\b)(?!I'd like\b)/gi,
    "$1\n\n",
  );

  // Space before "Name - Firm" mid-flow (no prior punctuation)
  s = s.replace(/([^\n])\s+([A-Z][A-Za-z.'\-\s]{2,40}\s+-\s+[A-Z][^\n]{2,80})/g, "$1\n\n$2");

  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

/** Split on blank lines; then break on speaker-style lines when needed. */
function splitIntoParagraphsNormalized(text: string): string[] {
  const t = text.trim();
  if (!t) return [];

  let blocks = t
    .split(/\n{2,}/)
    .map((x) => x.trim())
    .filter(Boolean);

  const shouldSpeakerWalk = (chunk: string) =>
    chunk.length > 400 && chunk.includes("\n");

  if (blocks.length === 1 && shouldSpeakerWalk(blocks[0])) {
    const lines = blocks[0].split("\n");
    const out: string[] = [];
    let cur = "";
    for (const line of lines) {
      if (SPEAKER_LINE_RE.test(line.trim()) && cur) {
        out.push(cur.trim());
        cur = line;
      } else {
        cur = cur ? `${cur}\n${line}` : line;
      }
    }
    if (cur) out.push(cur.trim());
    if (out.length > 1) blocks = out;
  }

  // Still one giant line with no newlines: chunk by sentence for readability
  if (blocks.length === 1 && blocks[0].length > 3500 && !blocks[0].includes("\n")) {
    blocks = chunkBySentence(blocks[0], 550);
  }

  return blocks;
}

/** Last resort: break a monolith into ~maxLen character chunks on sentence ends. */
function chunkBySentence(text: string, maxLen: number): string[] {
  const parts = text.match(/[^.!?]+(?:[.!?]+|$)/g) || [text];
  const out: string[] = [];
  let cur = "";
  for (const p of parts) {
    const piece = p.trim();
    if (!piece) continue;
    if (cur.length + piece.length > maxLen && cur) {
      out.push(cur.trim());
      cur = piece;
    } else {
      cur = cur ? `${cur} ${piece}` : piece;
    }
  }
  if (cur) out.push(cur.trim());
  return out.length > 1 ? out : [text];
}

/** Q&A: wider detection of new turns (colon lines, name–firm, operator, ? boundaries). */
function splitQATurnsNormalized(text: string): string[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const turns: string[] = [];
  let cur: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (isQASpeakerOrHandoffLine(trimmed) && cur.length > 0) {
      turns.push(cur.join("\n").trim());
      cur = [line];
    } else {
      cur.push(line);
    }
  }
  if (cur.length) turns.push(cur.join("\n").trim());
  return turns.filter(Boolean);
}

function scoreQuestionSignals(text: string): number {
  let s = 0;
  const t = text.trim();
  const firstLine = (t.split("\n")[0] ?? "").trim();
  const qCount = (text.match(/\?/g) || []).length;
  if (qCount >= 1) s += 2;
  if (qCount >= 2) s += 2;
  if (/\b(from the line of|from the floor|your question|analyst|caller|participant)\b/i.test(text)) s += 2;
  if (/[A-Z][a-zA-Z.'\-\s]{2,40}\s+-\s+[A-Z][A-Za-z]/.test(firstLine)) s += 4;
  if (/^(?:Operator|Moderator|Host|Coordinator)\b/i.test(firstLine)) s += 3;
  if (/your next question|next question comes|please go ahead|\bgo ahead\b/i.test(t)) s += 2;
  if (t.length < 550 && qCount >= 1) s += 2;
  if (/^(?:Hi|Hey|Hello),?\b/i.test(firstLine) && qCount >= 1) s += 1;
  return s;
}

function scoreAnswerSignals(text: string): number {
  let s = 0;
  const t = text.trim();
  const firstLine = (t.split("\n")[0] ?? "").trim();
  const qCount = (text.match(/\?/g) || []).length;
  if (/^(?:thank you|thanks|thanks,|yes,|sure,|absolutely|great question|good question|appreciate)/i.test(firstLine))
    s += 3;
  if (
    /\b(we're pleased|we are pleased|we delivered|we expect|we believe|our guidance|we saw|we continue|we had|looking ahead)\b/i.test(
      text,
    )
  )
    s += 2;
  if (t.length > 650 && qCount === 0) s += 2;
  if (t.length > 1000 && qCount <= 1 && !/\bline of\b/i.test(text)) s += 1;
  return s;
}

/**
 * Heuristic Q vs A (audience / sell-side vs management). Uses wording, punctuation,
 * and alternation when unclear — not perfect on messy transcripts.
 */
export function labelQATurns(turns: string[]): { text: string; role: "q" | "a" }[] {
  let prev: "q" | "a" | null = null;
  const out: { text: string; role: "q" | "a" }[] = [];
  for (const text of turns) {
    const qS = scoreQuestionSignals(text);
    const aS = scoreAnswerSignals(text);
    let role: "q" | "a";
    if (qS >= aS + 2) role = "q";
    else if (aS >= qS + 2) role = "a";
    else if (prev === "q") role = "a";
    else if (prev === "a") role = "q";
    else role = qS >= aS ? "q" : "a";
    out.push({ text, role });
    prev = role;
  }
  return out;
}

/** If Q&A is still one blob, split on double newlines or single-line ? / handoff patterns. */
function splitQAFallbackMonolith(text: string): string[] {
  const byPara = text
    .split(/\n{2,}/)
    .map((x) => x.trim())
    .filter(Boolean);
  if (byPara.length > 1) return byPara;

  const only = byPara[0] ?? text.trim();
  if (only.length < 1200) return [only];

  // Single line or few breaks: split on ? + space + capital (likely new turn)
  const chunks = only.split(/(?<=\?)\s+(?=[A-Z][a-z]{2,18}\b)/g).map((x) => x.trim()).filter(Boolean);
  if (chunks.length > 1) return chunks;

  return chunkBySentence(only, 380);
}

function looksLikeManagementAnswerStart(text: string): boolean {
  const first = (text.split("\n")[0] ?? "").trim();
  return /^(thank you|thanks|thanks,|yes,|sure,|absolutely|great question|good question)/i.test(first);
}

/** Prior chunk still reads as audience / operator / question side (not exec answer). */
function looksQuestionSideChunk(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (/\?/.test(t)) return true;
  if (
    /\b(from the line of|from the floor|next question comes|your next question|the next question|our next question|please go ahead|analyst|caller)\b/i.test(
      t,
    )
  )
    return true;
  return false;
}

/** Next paragraph starts a new moderated question (not a follow-on from same analyst). */
function looksLikeFreshHandoffParagraph(n: string): boolean {
  return /^(our next question|the next question|your next question|first question|second question|follow[- ]?up question)\b/i.test(
    n.trim(),
  );
}

/**
 * Recombine fragments caused by aggressive Q&A preprocessing (e.g. moderator intro split,
 * "Please go ahead" on its own line, multi-part analyst questions split on ? or paragraphs).
 */
function mergeQuestionFragments(turns: string[]): string[] {
  if (turns.length <= 1) return turns;
  const out: string[] = [];
  let acc = turns[0] ?? "";
  for (let k = 1; k < turns.length; k++) {
    const nxt = turns[k] ?? "";
    if (shouldMergeQuestionFragments(acc, nxt)) {
      acc = `${acc}\n\n${nxt}`;
    } else {
      out.push(acc.trim());
      acc = nxt;
    }
  }
  out.push(acc.trim());
  return out.filter(Boolean);
}

function shouldMergeQuestionFragments(prev: string, next: string): boolean {
  const p = prev.trimEnd();
  const n = next.trim();
  if (!p || !n) return false;

  if (looksLikeManagementAnswerStart(p) || looksLikeManagementAnswerStart(n)) return false;

  if (/\?/.test(p) && looksLikeFreshHandoffParagraph(n)) return false;

  if (/\bcomes\s*$/i.test(p) && /^from the line of/i.test(n)) return true;
  if (/question comes\s*$/i.test(p) && /^from\b/i.test(n)) return true;

  if (/from the line of/i.test(p) && /^please go ahead\b/i.test(n)) return true;

  if (/^please go ahead\b/i.test(n) && !looksLikeManagementAnswerStart(p)) {
    if (looksQuestionSideChunk(p)) return true;
    // Orphan bank / firm-only line before the operator cue
    if (/\bwith\s+[A-Z][A-Za-z0-9.&\s]+\s*\.?\s*$/i.test(p.trimEnd())) return true;
  }

  if (looksQuestionSideChunk(p) && /^(and |or |also |then |just |finally )/i.test(n)) return true;

  if (
    !/\?/.test(p) &&
    p.length < 280 &&
    n.length > 30 &&
    !/^thank you\b/i.test(n) &&
    /\b(next question|line of|go ahead|moderator|operator|coordinator)\b/i.test(p)
  )
    return true;

  return false;
}

function endsWithSentenceEnd(s: string): boolean {
  return /[.!?…]["']?\s*$/i.test(s.trimEnd());
}

/**
 * Merge tiny stubs left after preprocessing ("Thank you." alone, "On your" + "first question…")
 * so one speaker isn't split across three Q/A blocks.
 */
function mergeMicroFragments(turns: string[]): string[] {
  if (turns.length <= 1) return turns;
  const out: string[] = [];
  let acc = turns[0] ?? "";
  for (let k = 1; k < turns.length; k++) {
    const nxt = turns[k] ?? "";
    if (shouldMergeMicroFragment(acc, nxt)) {
      acc = `${acc}\n\n${nxt}`;
    } else {
      out.push(acc.trim());
      acc = nxt;
    }
  }
  out.push(acc.trim());
  return out.filter(Boolean);
}

function shouldMergeMicroFragment(prev: string, next: string): boolean {
  const p = prev.trim();
  const n = next.trim();
  if (!p || !n) return false;
  if (looksLikeFreshHandoffParagraph(n)) return false;
  if (/^(please go ahead|your next question|the next question|our next question)\b/i.test(n)) return false;

  if (/^(thank you|thanks)[.!]?\s*$/i.test(p)) return true;

  if (/\?/.test(p)) return false;
  if (SPEAKER_LINE_RE.test(p)) return false;
  if (QA_NAME_FIRM_LINE_RE.test(p)) return false;
  if (/\bfrom the line of\b/i.test(p)) return false;

  if (p.length <= 52 && !endsWithSentenceEnd(p)) {
    if (/^[a-z]/.test(n)) return true;
    if (/^on\s+your\s*$/i.test(p)) return true;
  }

  return false;
}

/** Within one paragraph block, split when the same speaker moves to a new sub-topic. */
export function splitTopicSegments(paragraph: string): string[] {
  const lines = paragraph.replace(/\r\n/g, "\n").split("\n");
  const chunks: string[][] = [];
  let cur: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (TOPIC_LINE_RE.test(trimmed) && cur.length > 0) {
      chunks.push(cur);
      cur = [line];
    } else {
      cur.push(line);
    }
  }
  if (cur.length) chunks.push(cur);
  return chunks.map((c) => c.join("\n").trim()).filter(Boolean);
}

export type TranscriptBlock =
  | { kind: "qa-turn"; text: string; index: number; role: "q" | "a" }
  | { kind: "body"; text: string; topicDepth: 0 | 1 };

/** Build flat list of render units for a section. */
export function buildTranscriptBlocks(sectionType: string, text: string): TranscriptBlock[] {
  const normalized = preprocessTranscript(text);

  if (sectionType === "qa") {
    const qaReady = preprocessQASection(normalized);
    let turns = splitQATurnsNormalized(qaReady);
    if (turns.length <= 1) {
      turns = splitQAFallbackMonolith(qaReady);
    }
    turns = mergeQuestionFragments(turns);
    turns = mergeMicroFragments(turns);
    const labeled = labelQATurns(turns);
    return labeled.map((row, i) => ({
      kind: "qa-turn" as const,
      text: row.text,
      index: i,
      role: row.role,
    }));
  }

  const paras = splitIntoParagraphsNormalized(normalized);
  const out: TranscriptBlock[] = [];
  for (const para of paras) {
    const segments = splitTopicSegments(para);
    if (segments.length <= 1) {
      out.push({ kind: "body", text: para, topicDepth: 0 });
    } else {
      segments.forEach((seg, j) => {
        out.push({ kind: "body", text: seg, topicDepth: j === 0 ? 0 : 1 });
      });
    }
  }
  return out;
}
