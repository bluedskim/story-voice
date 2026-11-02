#!/usr/bin/env python3
"""Speaker markup parse/strip and speaker-aware segmentation tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from story_catalog import load_story
from story_segmentation import split_story_into_chunks
from story_speaker_markup import parse_speaker_line, strip_speaker_markup


def test_parse_and_strip() -> None:
    key, rest = parse_speaker_line('@놀부: "안녕!"')
    assert key == "놀부"
    assert rest == '"안녕!"'
    assert parse_speaker_line("plain line") == (None, "plain line")
    raw = '@흥부: 첫 줄\n둘째 줄\n@제비: "짹짹"'
    stripped = strip_speaker_markup(raw)
    assert stripped == '첫 줄\n둘째 줄\n"짹짹"'


def test_heungbu_strip_matches_display_body() -> None:
    path = ROOT / "content" / "stories" / "heungbu-nolbu.txt"
    from story_catalog import FRONTMATTER_RE

    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    assert match
    markup_body = raw[match.end() :].strip()
    body_from_catalog = load_story(path).body
    assert strip_speaker_markup(markup_body) == body_from_catalog
    assert "@" not in body_from_catalog


def test_no_speaker_merge_across_lines() -> None:
    """Two @speaker lines must never become one chunk even when short."""
    text = "@흥부: 짧아.\n@놀부: 또 짧아."
    chunks = split_story_into_chunks(text, max_chars=120)
    assert len(chunks) == 2
    assert [c.speaker_key for c in chunks] == ["흥부", "놀부"]
    text = "\n".join(
        [
            "@흥부: " + "가" * 50 + ". " + "나" * 50 + ".",
            '@놀부: "짧은 대사"',
        ]
    )
    chunks = split_story_into_chunks(text, max_chars=120)
    for c in chunks:
        assert c.speaker_key in ("흥부", "놀부")
    assert any(c.speaker_key == "흥부" for c in chunks)
    assert any(c.speaker_key == "놀부" for c in chunks)
    dialogue = [c for c in chunks if c.role == "dialogue"]
    assert len(dialogue) == 1 and dialogue[0].speaker_key == "놀부"


def test_heungbu_catalog_chunks_unchanged_for_stripped_body() -> None:
    story = load_story(ROOT / "content" / "stories" / "heungbu-nolbu.txt")
    chunks = split_story_into_chunks(story.body, max_chars=120)
    texts = [c.text for c in chunks]
    assert any("욕심만 부리면" in t for t in texts)
    assert all("@" not in t for t in texts)


def main() -> int:
    test_parse_and_strip()
    test_heungbu_strip_matches_display_body()
    test_no_speaker_merge_across_lines()
    test_heungbu_catalog_chunks_unchanged_for_stripped_body()
    print("OK: story speaker markup tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
