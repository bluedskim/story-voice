#!/usr/bin/env python3
"""Story narration/dialogue segmentation tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from story_segmentation import (
    list_dialogue_segments,
    segment_line,
    segment_story_text,
    split_story_into_chunks,
)


def test_mixed_line_splits_dialogue() -> None:
    segs = segment_line('형은 말했어요. "아우야!"')
    assert len(segs) == 2
    assert segs[0].role == "narration"
    assert segs[0].text == "형은 말했어요."
    assert segs[1].role == "dialogue"
    assert segs[1].text == "아우야!"


def test_unmatched_quote_stays_narration() -> None:
    segs = segment_line('그는 말했어요. "끝나지 않은')
    assert all(s.role == "narration" for s in segs)
    assert any('"끝나지 않은' in s.text for s in segs)


def test_dialogue_is_own_chunk() -> None:
    text = '앞 문장입니다. "대사 한 줄"\n다음 문단.'
    chunks = split_story_into_chunks(text, max_chars=120)
    roles = [c.role for c in chunks]
    assert "dialogue" in roles
    dialogue_chunks = [c for c in chunks if c.role == "dialogue"]
    assert len(dialogue_chunks) == 1
    assert dialogue_chunks[0].text == "대사 한 줄"
    assert all(c.role != "dialogue" or c.text == "대사 한 줄" for c in chunks)


def test_multiple_sentences_pack_narration() -> None:
    text = "하나. 둘. 셋. 넷."
    chunks = split_story_into_chunks(text, max_chars=8)
    narration = [c for c in chunks if c.role == "narration"]
    assert len(narration) >= 2


def test_ui_joeun_hyeongje_dialogue_list() -> None:
    story = (ROOT / "content" / "stories" / "ui-joeun-hyeongje.txt").read_text(encoding="utf-8")
    body = story.split("---", 2)[-1]
    lines = list_dialogue_segments(body)
    assert lines == [
        "아우는 이제 막 살림을 차렸으니 쌀이 더 필요할 거야.",
        "형님은 식구가 많으니 쌀이 더 필요하실 거야.",
        "이상하다, 분명히 갖다 놓았는데.",
    ]


def test_curly_quotes() -> None:
    segs = segment_line("“안녕!”")
    assert len(segs) == 1
    assert segs[0].role == "dialogue"
    assert segs[0].text == "안녕!"


def main() -> int:
    test_mixed_line_splits_dialogue()
    test_unmatched_quote_stays_narration()
    test_dialogue_is_own_chunk()
    test_multiple_sentences_pack_narration()
    test_ui_joeun_hyeongje_dialogue_list()
    test_curly_quotes()
    print("OK: story segmentation tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
