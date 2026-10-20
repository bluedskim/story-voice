"""Story body text for narration (YAML front matter stripped)."""

from __future__ import annotations

from pathlib import Path

from story_catalog import load_story


def narration_text_from_path(path: Path) -> str:
    """Return story body only; never narrate catalog front matter."""
    return load_story(path).body


def narration_text_from_string(raw: str) -> str:
    """Strip front matter when present in raw file contents."""
    from story_catalog import _parse_frontmatter

    _, body = _parse_frontmatter(raw)
    return body
