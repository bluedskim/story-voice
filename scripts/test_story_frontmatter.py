#!/usr/bin/env python3
"""Regression: catalog story files must not send YAML front matter to TTS."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_story import read_story_text, story_chunks_for_tts


def test_explicit_story_cli_strips_frontmatter() -> None:
    path = ROOT / "content" / "stories" / "ui-joeun-hyeongje.txt"
    # Legacy CLI used catalog_mode=False and previously read raw file including YAML.
    text = read_story_text(path, catalog_mode=False)
    assert "title:" not in text.splitlines()[0:3]
    assert not text.strip().startswith("---")
    assert "옛날 옛적" in text

    chunk_texts = [c[0] for c in story_chunks_for_tts(text, 120)]
    joined = "\n".join(chunk_texts)
    assert "---" not in joined
    assert "title:" not in joined
    assert "id: ui-joeun-hyeongje" not in joined
    assert "order: 1" not in joined
    assert any("옛날 옛적" in t for t in chunk_texts)


def main() -> int:
    test_explicit_story_cli_strips_frontmatter()
    print("OK: story front matter regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
