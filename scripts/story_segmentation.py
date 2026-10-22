"""Story text → narration/dialogue segments and TTS chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from audio_quality_config import DEFAULT_MAX_CHARS

# Opening → closing quote pairs (double + single, ASCII + curly)
_OPENERS = {
    '"': '"',
    "“": "”",
    "'": "'",
    "‘": "’",
}
_CLOSERS = {v: k for k, v in _OPENERS.items()}

SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？…])\s+")


@dataclass(frozen=True)
class TextSegment:
    text: str
    role: str  # "narration" | "dialogue"


@dataclass(frozen=True)
class StoryChunk:
    text: str
    pause_after: str  # sentence | paragraph
    role: str


def _find_next_opener(text: str, start: int) -> int:
    best = -1
    for ch in _OPENERS:
        idx = text.find(ch, start)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    return best


def segment_line(line: str) -> list[TextSegment]:
    """Split one line into ordered narration/dialogue segments (quotes stripped for dialogue)."""
    line = line.strip()
    if not line:
        return []
    segments: list[TextSegment] = []
    i = 0
    while i < len(line):
        opener_idx = _find_next_opener(line, i)
        if opener_idx == -1:
            tail = line[i:].strip()
            if tail:
                segments.append(TextSegment(tail, "narration"))
            break
        if opener_idx > i:
            lead = line[i:opener_idx].strip()
            if lead:
                segments.append(TextSegment(lead, "narration"))
        open_ch = line[opener_idx]
        close_ch = _OPENERS[open_ch]
        close_idx = line.find(close_ch, opener_idx + 1)
        if close_idx == -1:
            # Unmatched quote → treat remainder as narration (per spec)
            rest = line[opener_idx:].strip()
            if rest:
                segments.append(TextSegment(rest, "narration"))
            break
        inner = line[opener_idx + 1 : close_idx].strip()
        if inner:
            segments.append(TextSegment(inner, "dialogue"))
        i = close_idx + 1
    return segments


def segment_story_text(text: str) -> list[TextSegment]:
    text = re.sub(r"[ \t]+", " ", text.strip())
    segments: list[TextSegment] = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        for seg in segment_line(para):
            if segments and segments[-1].role == seg.role == "narration":
                segments[-1] = TextSegment(f"{segments[-1].text} {seg.text}".strip(), "narration")
            else:
                segments.append(seg)
    return segments


def _pack_narration(sentences: list[str], max_chars: int) -> list[str]:
    if not sentences:
        return []
    packed: list[str] = []
    buf = sentences[0]
    for s in sentences[1:]:
        if len(buf) + 1 + len(s) > max_chars:
            packed.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        packed.append(buf)
    return packed


def split_story_into_chunks(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[StoryChunk]:
    chunks: list[StoryChunk] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text.strip()) if p.strip()]
    for para in paragraphs:
        line_segments = segment_line(para)
        para_chunks: list[StoryChunk] = []
        for seg in line_segments:
            if seg.role == "dialogue":
                para_chunks.append(StoryChunk(seg.text, "sentence", "dialogue"))
                continue
            sents = [s.strip() for s in SENTENCE_END_RE.split(seg.text) if s.strip()]
            for part in _pack_narration(sents, max_chars):
                para_chunks.append(StoryChunk(part, "sentence", "narration"))
        if para_chunks:
            last = para_chunks[-1]
            para_chunks[-1] = StoryChunk(last.text, "paragraph", last.role)
        chunks.extend(para_chunks)
    return chunks


def list_dialogue_segments(text: str) -> list[str]:
    return [s.text for s in segment_story_text(text) if s.role == "dialogue"]


# Backward-compatible API for generation_backends / tests
def split_sentences(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[tuple[str, str]]:
    return [(c.text, c.pause_after) for c in split_story_into_chunks(text, max_chars)]
