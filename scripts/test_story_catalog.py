#!/usr/bin/env python3
"""Catalog sanity: story ids, order, front matter, length, and frontend motifs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_story import story_chunks_for_tts
from story_catalog import list_stories

STORY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXPECTED = [
    ("ui-joeun-hyeongje", "의좋은 형제"),
    ("geum-dokki-eun-dokki", "금도끼 은도끼"),
    ("hokburi-yeonggam", "혹부리 영감"),
]


def test_catalog_ids_titles_and_order() -> None:
    stories = list_stories()
    assert [(s.id, s.title) for s in stories] == EXPECTED
    assert [s.order for s in stories] == [1, 2, 3]
    for s in stories:
        assert STORY_ID_RE.match(s.id), s.id
        assert s.path.stem == s.id, (s.path, s.id)


def test_story_bodies_are_clean_and_similar_length() -> None:
    stories = list_stories()
    base = len(stories[0].body)
    for s in stories:
        assert not s.body.startswith("---")
        assert "title:" not in s.body and "id:" not in s.body
        # Keep stories near the reference length (의좋은 형제).
        assert 0.75 * base <= len(s.body) <= 1.3 * base, (s.id, len(s.body), base)
        assert "잘 자요" not in s.body and "쿨쿨" not in s.body, s.id
        chunks = [c[0] for c in story_chunks_for_tts(s.body, 120)]
        assert chunks and all(c.strip() for c in chunks)


def test_frontend_motifs_cover_catalog() -> None:
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const STORY_MOTIFS = \{(.*?)\};", app_js, re.DOTALL)
    assert block
    keys = set(re.findall(r'"([a-z0-9-]+)"\s*:', block.group(1)))
    assert keys == {s.id for s in list_stories()}, keys


def main() -> int:
    test_catalog_ids_titles_and_order()
    test_story_bodies_are_clean_and_similar_length()
    test_frontend_motifs_cover_catalog()
    print("OK: story catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
