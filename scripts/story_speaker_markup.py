"""PoC speaker prefixes in story lines (@흥부: …). Stripped for catalog / single-voice TTS."""

from __future__ import annotations

import re

# Line-start tag: @speaker_key: rest (speaker_key is non-empty, no spaces/colons)
SPEAKER_LINE_RE = re.compile(r"^@([^:\s]+):\s*(.*)$", re.DOTALL)


def parse_speaker_line(line: str) -> tuple[str | None, str]:
    """Return (speaker_key, content). content is the line without the @key: prefix."""
    stripped = line.strip()
    if not stripped:
        return None, ""
    m = SPEAKER_LINE_RE.match(stripped)
    if not m:
        return None, stripped
    key = m.group(1).strip()
    rest = m.group(2)
    return (key or None), rest


def strip_speaker_markup(text: str) -> str:
    """Remove @speaker: prefixes line-by-line; preserves paragraph breaks."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        _key, content = parse_speaker_line(line)
        if content or not line.strip():
            out.append(content if line.strip() else line)
        else:
            out.append("")
    return "\n".join(out).strip()


def has_speaker_markup(text: str) -> bool:
    return any(SPEAKER_LINE_RE.match(ln.strip()) for ln in text.splitlines() if ln.strip())


def iter_tagged_lines(text: str) -> list[tuple[str, str]]:
    """Lines with @speaker: prefix → (speaker_key, content after prefix)."""
    tagged: list[tuple[str, str]] = []
    for line in text.splitlines():
        key, content = parse_speaker_line(line)
        if key is not None:
            tagged.append((key, content))
    return tagged


def is_quoted_dialogue_content(content: str) -> bool:
    """True when content is only quoted speech (one dialogue segment)."""
    from story_segmentation import segment_line

    content = content.strip()
    if not content:
        return False
    segs = segment_line(content)
    return len(segs) == 1 and segs[0].role == "dialogue"


def assert_markup_lines_are_quoted_dialogue(text: str) -> None:
    for key, content in iter_tagged_lines(text):
        if not is_quoted_dialogue_content(content):
            raise AssertionError(f"@{key}: line is not quoted dialogue only: {content!r}")
