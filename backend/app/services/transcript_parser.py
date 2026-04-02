from __future__ import annotations

import re


_SPEAKER_LINE_RE = re.compile(r"^(?P<name>[A-Z][A-Za-z\.\-'\s]{2,80}):\s+(?P<rest>.+)$")


def parse_sections(raw_text: str) -> list[dict]:
    """
    Baseline parser:
    - Split into operator intro, prepared remarks, Q&A using simple anchors.
    - Within each section, capture speaker for the first speaker-like line if present.
    """
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]

    joined = "\n".join(lines)
    lower = joined.lower()

    qa_idx = None
    for marker in ["question-and-answer", "question and answer", "q&a", "questions and answers"]:
        m = lower.find(marker)
        if m != -1:
            qa_idx = m
            break

    # Crude segmentation: everything before Q&A is "prepared_remarks" (with a short operator intro prefix)
    operator_intro_text = ""
    prepared_text = joined
    qa_text = ""

    if qa_idx is not None:
        prepared_text = joined[:qa_idx].strip()
        qa_text = joined[qa_idx:].strip()

    # Operator intro: first ~60 lines or until first obvious exec speaker line
    prepared_lines = prepared_text.split("\n")
    cut = min(60, len(prepared_lines))
    for i in range(cut):
        if _SPEAKER_LINE_RE.match(prepared_lines[i]):
            cut = i
            break
    operator_intro_text = "\n".join(prepared_lines[:cut]).strip()
    prepared_text2 = "\n".join(prepared_lines[cut:]).strip()

    sections: list[dict] = []
    order = 0

    if operator_intro_text:
        sections.append(
            {
                "section_type": "operator_intro",
                "speaker": "Operator",
                "text": operator_intro_text,
                "order": order,
            }
        )
        order += 1

    if prepared_text2:
        speaker = _first_speaker(prepared_text2)
        sections.append(
            {
                "section_type": "prepared_remarks",
                "speaker": speaker,
                "text": prepared_text2,
                "order": order,
            }
        )
        order += 1

    if qa_text:
        sections.append(
            {
                "section_type": "qa",
                "speaker": None,
                "text": qa_text,
                "order": order,
            }
        )

    # Fallback: if we couldn't meaningfully segment (common when transcripts don't use "Name: " lines),
    # return a single prepared_remarks section containing the full text.
    if not sections or (len(sections) == 1 and sections[0]["section_type"] == "operator_intro"):
        return [
            {
                "section_type": "prepared_remarks",
                "speaker": None,
                "text": joined,
                "order": 0,
            }
        ]

    return sections


def _first_speaker(text: str) -> str | None:
    for ln in text.split("\n")[:80]:
        m = _SPEAKER_LINE_RE.match(ln.strip())
        if m:
            return m.group("name").strip()
    return None

