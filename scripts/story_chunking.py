"""Sentence-based story chunking for TTS."""

from __future__ import annotations

import re
from dataclasses import dataclass

from audio_quality_config import (
    DIALOGUE_PAUSE_EXTRA,
    LONG_SENTENCE_COMMA_SPLIT_CHARS,
    MIN_SENTENCE_MERGE_CHARS,
    TARGET_CHUNK_MAX_CHARS,
    TARGET_CHUNK_MIN_CHARS,
)

SENTENCE_END_RE = re.compile(r"(?<=[.!?。！？…])\s+")
DIALOGUE_MARK_RE = re.compile(r'["“”‘’「」『』]')
DIALOGUE_SPAN_RE = re.compile(
    r'(["“”])(.+?)(["“”])|([「『])(.+?)([」』])'
)


@dataclass(frozen=True)
class StoryChunk:
    text: str
    pause_after: str  # "sentence" | "paragraph"
    dialogue: bool

    @property
    def pause_before_sec(self) -> float:
        return DIALOGUE_PAUSE_EXTRA if self.dialogue else 0.0

    def pause_after_sec(self, sentence_pause: float, paragraph_pause: float) -> float:
        base = paragraph_pause if self.pause_after == "paragraph" else sentence_pause
        if self.dialogue:
            base += DIALOGUE_PAUSE_EXTRA
        return base


@dataclass(frozen=True)
class _Segment:
    text: str
    dialogue: bool
    pause_after: str


def _is_dialogue(text: str) -> bool:
    return bool(DIALOGUE_MARK_RE.search(text))


def _split_dialogue_spans(sentence: str) -> list[str]:
    """Pull quoted dialogue into its own segments for TTS pauses."""
    if not DIALOGUE_MARK_RE.search(sentence):
        return [sentence]
    parts: list[str] = []
    pos = 0
    for match in DIALOGUE_SPAN_RE.finditer(sentence):
        if match.start() > pos:
            lead = sentence[pos : match.start()].strip()
            if lead:
                parts.append(lead)
        parts.append(match.group(0).strip())
        pos = match.end()
    if pos < len(sentence):
        tail = sentence[pos:].strip()
        if tail:
            parts.append(tail)
    return parts or [sentence]


def _split_long_at_commas(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    parts: list[str] = []
    buf = ""
    for segment in re.split(r"([,，])", sentence):
        if segment in {",", "，"}:
            if buf:
                buf += segment
            continue
        candidate = f"{buf}{segment}".strip() if buf else segment.strip()
        if buf and len(candidate) > max_chars:
            parts.append(buf.strip())
            buf = segment.strip()
        else:
            buf = candidate
    if buf:
        parts.append(buf.strip())
    return parts or [sentence]


def _merge_short(sentences: list[str], min_chars: int) -> list[str]:
    if not sentences:
        return []
    merged: list[str] = []
    buf = sentences[0]
    for s in sentences[1:]:
        can_merge = (
            len(buf) < min_chars
            and not _is_dialogue(buf)
            and not _is_dialogue(s)
        )
        if can_merge:
            buf = f"{buf} {s}".strip()
        else:
            merged.append(buf)
            buf = s
    if merged and len(buf) < min_chars and not _is_dialogue(buf) and not _is_dialogue(merged[-1]):
        merged[-1] = f"{merged[-1]} {buf}".strip()
    else:
        merged.append(buf)
    return merged


def _pack_segments(
    segments: list[_Segment],
    min_chars: int,
    max_chars: int,
) -> list[StoryChunk]:
    """Pack narration segments up to max_chars; dialogue always standalone."""
    chunks: list[StoryChunk] = []
    buf: list[_Segment] = []

    def packed_len(parts: list[_Segment]) -> int:
        return len(" ".join(p.text for p in parts))

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        text = " ".join(p.text for p in buf)
        chunks.append(
            StoryChunk(
                text=text,
                pause_after=buf[-1].pause_after,
                dialogue=any(p.dialogue for p in buf),
            )
        )
        buf = []

    for seg in segments:
        if seg.dialogue:
            flush()
            chunks.append(StoryChunk(text=seg.text, pause_after=seg.pause_after, dialogue=True))
            continue
        if buf and (
            packed_len(buf) + 1 + len(seg.text) > max_chars or buf[-1].pause_after == "paragraph"
        ):
            flush()
        buf.append(seg)
        if packed_len(buf) >= min_chars or seg.pause_after == "paragraph":
            flush()
    flush()
    return chunks


def split_story_into_chunks(
    text: str,
    long_sentence_chars: int = LONG_SENTENCE_COMMA_SPLIT_CHARS,
    min_merge_chars: int = MIN_SENTENCE_MERGE_CHARS,
    target_min_chars: int = TARGET_CHUNK_MIN_CHARS,
    target_max_chars: int = TARGET_CHUNK_MAX_CHARS,
) -> list[StoryChunk]:
    text = re.sub(r"[ \t]+", " ", text.strip())
    if not text:
        return []
    segments: list[_Segment] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    for para in paragraphs:
        raw_sents = [s.strip() for s in SENTENCE_END_RE.split(para) if s.strip()]
        expanded: list[str] = []
        for s in raw_sents:
            for span in _split_dialogue_spans(s):
                expanded.extend(_split_long_at_commas(span, long_sentence_chars))
        merged = _merge_short(expanded, min_merge_chars)
        for ci, sent in enumerate(merged):
            pause_after = "paragraph" if ci == len(merged) - 1 else "sentence"
            segments.append(
                _Segment(
                    text=sent,
                    dialogue=_is_dialogue(sent),
                    pause_after=pause_after,
                )
            )
    return _pack_segments(segments, target_min_chars, target_max_chars)


def split_sentences(text: str, max_chars: int = 120) -> list[tuple[str, str]]:
    """Legacy API: returns (text, pause_kind) tuples."""
    return [(c.text, c.pause_after) for c in split_story_into_chunks(text, target_max_chars=max_chars)]
