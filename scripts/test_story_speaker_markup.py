#!/usr/bin/env python3
"""Speaker markup parse/strip and speaker-aware segmentation tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from story_catalog import FRONTMATTER_RE, load_story
from story_segmentation import split_story_into_chunks
from story_speaker_markup import (
    assert_markup_lines_are_quoted_dialogue,
    is_quoted_dialogue_content,
    iter_tagged_lines,
    parse_speaker_line,
    strip_speaker_markup,
)

# Canonical bodies before @speaker markup (strip(markup file) must match exactly).
HEUNGBU_CANONICAL_BODY = """\
옛날 옛적, 한 마을에 형 놀부와 동생 흥부가 살았어요.
놀부는 부자였지만 마음씨가 고약했고, 흥부는 가난했지만 늘 웃으며 이웃을 도왔답니다.
어느 봄날, 흥부는 다친 제비 한 마리를 발견하고 정성껏 치료해 주었어요.
가을이 되자 제비는 큰 박씨 하나를 물고 돌아왔지요.

흥부는 박씨를 마당 한구석에 심어 매일 물을 주었어요.
박이 여물자 흥부가 조심스레 박을 탔더니, 그 안에서 쌀과 옷감이 나왔어요.
흥부는 형님과 나누어 쓰려 했지만, 놀부는 부러워하며 제비를 잡아 다리를 부러뜨렸답니다.

놀부도 박씨를 얻어 심었어요.
그러나 놀부의 박에서는 도깨비들이 튀어나와 집을 어지럽혔어요.
"욕심만 부리면 선한 마음은 멀어진단다."
놀부는 고개를 숙이고 흥부에게 미안하다고 말했어요.

흥부는 놀부를 용서하고 함께 밥을 나누었어요.
놀부는 그 뒤로 욕심을 버리고 흥부처럼 이웃을 돕기 시작했답니다.
마을 사람들은 나눔과 정성이 진짜 보물이라고 말했어요."""

GEUM_DOKKI_CANONICAL_BODY = """\
옛날 옛적, 깊은 산속 마을에 마음씨 착한 나무꾼이 살았어요.
나무꾼은 날마다 산에 올라 나무를 하며 늙은 어머니를 모셨어요.
어느 날, 나무꾼은 맑은 연못가에서 나무를 베고 있었어요.
그런데 그만 손이 미끄러져 도끼가 연못에 퐁당 빠지고 말았어요.

"아이고, 이를 어쩌나. 하나밖에 없는 도끼인데."
나무꾼이 연못가에 앉아 엉엉 울고 있을 때였어요.
물결이 둥글게 일더니 하얀 수염의 산신령님이 나타났어요.
"이 금도끼가 네 도끼냐?"
"아니에요. 제 도끼는 그렇게 반짝이지 않아요."
"그럼 이 은도끼가 네 도끼냐?"
"아니에요. 제 도끼는 낡은 쇠도끼예요."

산신령님은 빙그레 웃으며 낡은 쇠도끼를 꺼내 주었어요.
"참 정직하구나. 이 도끼 세 개를 모두 가져가거라."
나무꾼은 고개 숙여 인사하고 기쁜 마음으로 집에 돌아갔어요.

이 이야기를 들은 욕심쟁이 이웃도 연못으로 달려갔어요.
그리고 일부러 도끼를 연못에 던져 넣었지요.
산신령님이 금도끼를 들고 나타나자, 욕심쟁이는 얼른 외쳤어요.
"네, 그게 바로 제 도끼예요!"
산신령님은 아무 말 없이 물속으로 사라졌어요.
욕심쟁이는 금도끼도, 자기 도끼도 모두 잃고 말았답니다.

나무꾼은 세 도끼로 부지런히 일하며 어머니를 정성껏 모셨어요.
마을 사람들은 정직한 마음이 그 어떤 보물보다 귀하다고 이야기했답니다."""


def _markup_body(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    assert match
    return raw[match.end() :].strip()


def test_parse_and_strip() -> None:
    key, rest = parse_speaker_line('@놀부: "안녕!"')
    assert key == "놀부"
    assert rest == '"안녕!"'
    assert is_quoted_dialogue_content(rest)
    assert parse_speaker_line("plain line") == (None, "plain line")
    raw = '@흥부: "첫 대사"\n둘째 줄\n@제비: "짹짹"'
    stripped = strip_speaker_markup(raw)
    assert stripped == '"첫 대사"\n둘째 줄\n"짹짹"'


def test_markup_stories_strip_to_canonical_and_tagged_lines_are_quotes() -> None:
    for story_id, canonical in (
        ("heungbu-nolbu", HEUNGBU_CANONICAL_BODY),
        ("geum-dokki-eun-dokki", GEUM_DOKKI_CANONICAL_BODY),
    ):
        path = ROOT / "content" / "stories" / f"{story_id}.txt"
        markup = _markup_body(path)
        assert strip_speaker_markup(markup) == canonical.strip()
        assert load_story(path).body == canonical.strip()
        assert_markup_lines_are_quoted_dialogue(markup)
        for _key, content in iter_tagged_lines(markup):
            assert is_quoted_dialogue_content(content)


def test_no_speaker_merge_across_lines() -> None:
    text = '@흥부: "짧아."\n@놀부: "또 짧아."'
    chunks = split_story_into_chunks(text, max_chars=120)
    assert len(chunks) == 2
    assert [c.speaker_key for c in chunks] == ["흥부", "놀부"]
    assert all(c.role == "dialogue" for c in chunks)


def test_heungbu_single_tagged_quote_chunk() -> None:
    path = ROOT / "content" / "stories" / "heungbu-nolbu.txt"
    story = load_story(path)
    markup = _markup_body(path)
    assert len(iter_tagged_lines(markup)) == 1
    chunks_markup = split_story_into_chunks(markup, max_chars=120)
    character = [c for c in chunks_markup if c.speaker_key is not None]
    narrator = [c for c in chunks_markup if c.speaker_key is None]
    assert len(character) == 1
    assert character[0].text == "욕심만 부리면 선한 마음은 멀어진단다."
    chunks_plain = split_story_into_chunks(story.body, max_chars=120)
    assert [c.text for c in chunks_plain] == [c.text for c in chunks_markup]
    assert [c.role for c in chunks_plain] == [c.role for c in chunks_markup]


def test_geum_dokki_seven_dialogue_chunks() -> None:
    markup = _markup_body(ROOT / "content" / "stories" / "geum-dokki-eun-dokki.txt")
    assert len(iter_tagged_lines(markup)) == 7
    chunks = split_story_into_chunks(markup, max_chars=120)
    character = [c for c in chunks if c.speaker_key is not None]
    narrator = [c for c in chunks if c.speaker_key is None]
    assert len(character) == 7
    assert len(narrator) >= 1


def main() -> int:
    test_parse_and_strip()
    test_markup_stories_strip_to_canonical_and_tagged_lines_are_quotes()
    test_no_speaker_merge_across_lines()
    test_heungbu_single_tagged_quote_chunk()
    test_geum_dokki_seven_dialogue_chunks()
    print("OK: story speaker markup tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
