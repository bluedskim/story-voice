#!/usr/bin/env python3
"""Catalog sanity: story ids, order, front matter, length, and frontend motifs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_story import story_chunks_for_tts
from story_catalog import list_stories, story_default_voice_from_meta

STORY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXPECTED = [
    ("ui-joeun-hyeongje", "의좋은 형제", "dana"),
    ("geum-dokki-eun-dokki", "금도끼 은도끼", "harry"),
    ("hokburi-yeonggam", "혹부리 영감", "seraphina"),
    ("horangi-wa-gotgam", "호랑이와 곶감", "harry"),
    ("eunhye-gapeun-kkachi", "은혜 갚은 까치", "dana"),
    ("tokki-ui-gan", "토끼의 간", "harry"),
    ("ureong-gaksi", "우렁각시", "dana"),
    ("cheong-gaeguri", "청개구리", "seraphina"),
    ("gyeonu-wa-jiknyeo", "견우와 직녀", "harry"),
    ("namukkun-gwa-seonnyeo", "나무꾼과 선녀", "dana"),
    ("gae-wa-goyangi-ui-guseul", "개와 고양이의 구슬", "seraphina"),
]


def test_catalog_ids_titles_and_order() -> None:
    stories = list_stories()
    assert [(s.id, s.title) for s in stories] == [(a, b) for a, b, _ in EXPECTED]
    assert [s.default_voice for s in stories] == [v for _, _, v in EXPECTED]
    assert [s.order for s in stories] == list(range(1, len(EXPECTED) + 1))
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


def test_default_voice_validation() -> None:
    assert story_default_voice_from_meta({"defaultVoice": "seraphina"}) == "seraphina"
    assert story_default_voice_from_meta({"defaultVoice": "Harry"}) == "harry"
    try:
        story_default_voice_from_meta({"defaultVoice": "unknown"})
    except ValueError as exc:
        assert "unsupported defaultVoice" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown defaultVoice")


def main() -> int:
    test_catalog_ids_titles_and_order()
    test_default_voice_validation()
    test_story_bodies_are_clean_and_similar_length()
    test_frontend_motifs_cover_catalog()
    print("OK: story catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
