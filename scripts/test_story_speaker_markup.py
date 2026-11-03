#!/usr/bin/env python3
"""Speaker markup parse/strip and speaker-aware segmentation tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from story_catalog import FRONTMATTER_RE, load_story, list_stories
from story_segmentation import split_story_into_chunks
from story_speaker_markup import (
    assert_markup_lines_are_quoted_dialogue,
    assert_untagged_lines_have_no_standalone_dialogue,
    is_quoted_dialogue_content,
    iter_tagged_lines,
    parse_speaker_line,
    strip_speaker_markup,
)

# Canonical bodies before @speaker markup (strip(markup file) must match exactly).
HORANGI_WA_GOTGAM_CANONICAL_BODY = """\
옛날 옛적, 산골짜기 작은 집에 아기와 엄마가 살았어요.
어느 날 밤, 아기가 갑자기 울음을 그치지 않았어요.
"으앙, 으앙!"
엄마는 아기를 안아 재우려 애썼지만 아기는 계속 울었어요.
엄마는 속삭이며 아기를 달랬어요.
"호랑이 온다, 호랑이 온다!"
아기는 잠깐 울음을 멈추고 주변을 두리번거렸어요.
그러고는 다시 울기 시작했지요.
엄마는 서랍에서 말린 곶감을 꺼내 아기에게 보여 주었어요.
엄마가 말했어요.
"자, 곶감 줄게. 곶감 먹고 울음 뚝 그치렴."
아기는 곶감을 받아들고 입에 넣더니 울음을 그쳤어요.

그 말을 들은 산속 호랑이는 깜짝 놀랐어요.
호랑이가 중얼거렸어요.
"곶감이라니, 호랑이보다 더 무서운 것이로구나!"
호랑이는 곶감이 무엇인지 알고 싶어 집 앞으로 살금살금 다가갔어요.
그때 어둠 속에서 소도둑이 나타났어요.
소도둑은 호랑이 등에 올라타며 소리쳤어요.
"내 소를 찾았다!"
호랑이는 등에 무언가 올라탄 것을 느끼고 깜짝 놀라 뛰었어요.
호랑이가 외쳤어요.
"이런, 곶감이 등에 올라탔어!"
호랑이는 산 너머까지 달아나 버렸고, 소도둑은 땅에 떨어져 어리둥절했어요.
그 뒤로 호랑이는 곶감이 무서워 다시는 그 마을에 내려오지 않았답니다.
"""

EUNHYE_GAPEUN_KKACHI_CANONICAL_BODY = """\
옛날 옛적, 과거를 보러 한양으로 가던 선비가 있었어요.
선비는 깊은 산길을 지나다 큰 구렁이가 까치 둥지를 향해 기어가는 것을 보았어요.
구렁이가 혀를 내밀며 말했어요.
"짹짹하는 새알, 맛있겠구나."
선비는 재빨리 활을 쏘아 구렁이를 물리쳤어요.
선비가 외쳤어요.
"이 새들은 내가 지킬 거야."
구렁이는 숨을 거두었고, 까치 새끼들은 무사했답니다.

해가 지자 선비는 산중에 있는 초가집에서 하룻밤 묵기로 했어요.
집주인 여인은 정갈한 밥을 내놓으며 말했어요.
"밤이 깊으니 이 방에서 쉬어 가세요."
선비는 방문을 닫고 잠자리에 누웠어요.
한밤중, 여인이 방문을 열고 들어왔어요.
선비는 여인의 눈이 초록빛으로 번뜩이는 것을 보고 깜짝 놀랐어요.
여인은 바로 낮에 죽은 구렁이의 아내였어요.
여인이 무서운 목소리로 말했어요.
"낮에 내 남편을 죽인 바로 그 선비군요."
여인은 선비를 묶어 두고 말했어요.
"날이 밝기 전에 저 산 위 빈 절의 종이 세 번 울리면 살려 주마."

선비는 절망 속에서 창밖을 바라보았어요.
그때 낮에 선비가 새끼를 구해 준 까치들이 빈 절의 종각으로 날아갔어요.
까치들은 몸으로 종을 세 번 세게 쳤어요.
둥, 둥, 둥, 종소리가 산골에 울려 퍼졌어요.
까치들은 힘을 다해 종을 치다 쓰러져 숨을 거두었답니다.
종소리를 들은 여인은 약속대로 선비를 풀어 주고 사라졌어요.
선비는 무사히 한양에 이르렀어요.
선비는 까치의 은혜를 잊지 않고 마을 사람들에게 이 이야기를 전했답니다.
"""

GEUM_DOKKI_CANONICAL_BODY = """\
옛날 옛적, 깊은 산속 마을에 마음씨 착한 나무꾼이 살았어요.
나무꾼은 날마다 산에 올라 나무를 하며 늙은 어머니를 모셨어요.
어느 날, 나무꾼은 맑은 연못가에서 나무를 베고 있었어요.
그런데 그만 손이 미끄러져 도끼가 연못에 퐁당 빠지고 말았어요.

나무꾼은 연못을 들여다보며 말했어요.
"아이고, 이를 어쩌나. 하나밖에 없는 도끼인데."
나무꾼이 연못가에 앉아 엉엉 울고 있을 때였어요.
물결이 둥글게 일더니 하얀 수염의 산신령님이 나타났어요.
산신령님이 금도끼를 들고 물었어요.
"이 금도끼가 네 도끼냐?"
나무꾼이 대답했어요.
"아니에요. 제 도끼는 그렇게 반짝이지 않아요."
산신령님이 이번에는 은도끼를 꺼내 물었어요.
"그럼 이 은도끼가 네 도끼냐?"
나무꾼이 또 대답했어요.
"아니에요. 제 도끼는 낡은 쇠도끼예요."

산신령님은 빙그레 웃으며 낡은 쇠도끼를 꺼내 주었어요.
산신령님이 말했어요.
"참 정직하구나. 이 도끼 세 개를 모두 가져가거라."
나무꾼은 고개 숙여 인사하고 기쁜 마음으로 집에 돌아갔어요.

이 이야기를 들은 욕심쟁이 이웃도 연못으로 달려갔어요.
그리고 일부러 도끼를 연못에 던져 넣었지요.
산신령님이 금도끼를 들고 나타나자, 욕심쟁이는 얼른 외쳤어요.
"네, 그게 바로 제 도끼예요!"
산신령님은 아무 말 없이 물속으로 사라졌어요.
욕심쟁이는 금도끼도, 자기 도끼도 모두 잃고 말았답니다.

나무꾼은 세 도끼로 부지런히 일하며 어머니를 정성껏 모셨어요.
마을 사람들은 정직한 마음이 그 어떤 보물보다 귀하다고 이야기했답니다.
"""

UI_JOEUN_HYEONGJE_CANONICAL_BODY = """\
옛날 옛적, 작은 산골 마을에 사이좋은 형과 아우가 살았어요.
형제는 봄부터 가을까지 함께 논에서 땀 흘려 일했어요.
가을이 되자 황금빛 벼가 잔뜩 여물었답니다.
형제는 벼를 똑같이 나누어 각자 집 앞에 볏단을 쌓았어요.

그날 밤, 형은 잠자리에 누워 생각했어요.
"아우는 이제 막 살림을 차렸으니 쌀이 더 필요할 거야."
형은 살금살금 일어나 볏단을 지고 아우네 집으로 갔어요.
그리고 아우의 볏단 위에 살며시 올려놓았지요.

그런데 같은 밤, 아우도 잠이 오지 않았어요.
아우는 이렇게 생각했어요.
"형님은 식구가 많으니 쌀이 더 필요하실 거야."
아우도 볏단을 지고 형네 집으로 조용히 걸어갔어요.

다음 날 아침, 형제는 깜짝 놀랐어요.
볏단이 하나도 줄지 않았거든요.
형이 볏단을 보며 말했어요.
"이상하다, 분명히 갖다 놓았는데."
그날 밤에도, 또 그다음 날 밤에도 형제는 볏단을 날랐어요.

사흘째 되는 밤, 둥근 달이 환하게 떠올랐어요.
볏단을 지고 가던 형제는 길 한가운데에서 딱 마주쳤어요.
서로의 얼굴을 본 형제는 모든 걸 알게 되었어요.
형과 아우는 볏단을 내려놓고 꼭 끌어안았답니다.

달님은 그 모습을 내려다보며 빙그레 웃었어요.
마을 사람들은 두 사람을 의좋은 형제라고 불렀어요.
형제는 그 뒤로도 서로를 먼저 생각하며 오래오래 사이좋게 지냈답니다.
"""

HOKBURI_YEONGGAM_CANONICAL_BODY = """\
옛날 옛적, 어느 마을에 턱에 커다란 혹이 달린 할아버지가 살았어요.
사람들은 할아버지를 혹부리 영감이라고 불렀어요.
할아버지는 노래를 아주 잘 불렀답니다.

어느 날, 할아버지는 산에서 나무를 하다가 그만 해가 저물었어요.
할아버지는 빈집에 들어가 하룻밤 쉬어 가기로 했어요.
심심해진 할아버지는 흥얼흥얼 노래를 불렀어요.
그때 문이 덜컥 열리더니 도깨비들이 우르르 몰려왔어요.

도깨비 하나가 할아버지에게 물었어요.
"할아버지, 그 고운 노래는 어디에서 나와요?"
할아버지는 웃으며 혹을 톡톡 두드렸어요.
할아버지가 대답했어요.
"노래는 바로 이 혹에서 나온단다."
도깨비들은 보물을 잔뜩 주고 혹을 똑 떼어 갔어요.
할아버지는 가벼운 얼굴로 신이 나서 집에 돌아왔어요.

이웃 마을에도 턱에 혹이 달린 욕심쟁이 영감이 있었어요.
욕심쟁이 영감은 보물을 얻으려고 그 빈집을 찾아갔어요.
그리고 도깨비들 앞에서 큰 소리로 노래를 불렀지요.
노래를 마친 욕심쟁이 영감이 말했어요.
"내 노래도 이 혹에서 나온단다. 보물을 주면 혹을 줄게."
도깨비들은 고개를 저었어요.
도깨비 하나가 외쳤어요.
"또 속을 줄 알고요? 이 혹이나 가져가세요!"
도깨비들은 지난번에 떼어 간 혹을 욕심쟁이 영감 턱에 척 붙였어요.
욕심쟁이 영감은 혹이 두 개가 되어 터덜터덜 돌아갔답니다.

착한 할아버지는 그 뒤로도 고운 노래를 흥얼거리며 즐겁게 지냈어요.
욕심쟁이 영감은 욕심을 부리면 있던 것도 잃는다는 걸 그제야 깨달았답니다.
"""

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
        ("horangi-wa-gotgam", HORANGI_WA_GOTGAM_CANONICAL_BODY),
        ("eunhye-gapeun-kkachi", EUNHYE_GAPEUN_KKACHI_CANONICAL_BODY),
        ("geum-dokki-eun-dokki", GEUM_DOKKI_CANONICAL_BODY),
        ("ui-joeun-hyeongje", UI_JOEUN_HYEONGJE_CANONICAL_BODY),
        ("hokburi-yeonggam", HOKBURI_YEONGGAM_CANONICAL_BODY),
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


def test_horangi_wa_gotgam_six_dialogue_lines() -> None:
    markup = _markup_body(ROOT / "content" / "stories" / "horangi-wa-gotgam.txt")
    tagged = iter_tagged_lines(markup)
    assert len(tagged) == 6
    assert [k for k, _ in tagged] == ["아기", "엄마", "엄마", "호랑이", "소도둑", "호랑이"]
    chunks = split_story_into_chunks(markup, max_chars=120)
    character = [c for c in chunks if c.speaker_key is not None]
    assert len(character) == 6


def test_eunhye_gapeun_kkachi_five_dialogue_lines() -> None:
    path = ROOT / "content" / "stories" / "eunhye-gapeun-kkachi.txt"
    story = load_story(path)
    markup = _markup_body(path)
    tagged = iter_tagged_lines(markup)
    assert len(tagged) == 5
    assert [k for k, _ in tagged] == ["구렁이", "선비", "여인", "여인", "여인"]
    chunks_markup = split_story_into_chunks(markup, max_chars=120)
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


def test_ui_joeun_hyeongje_three_dialogue_lines() -> None:
    markup = _markup_body(ROOT / "content" / "stories" / "ui-joeun-hyeongje.txt")
    tagged = iter_tagged_lines(markup)
    assert len(tagged) == 3
    assert [k for k, _ in tagged] == ["형", "아우", "형"]


def test_hokburi_yeonggam_four_dialogue_lines() -> None:
    markup = _markup_body(ROOT / "content" / "stories" / "hokburi-yeonggam.txt")
    tagged = iter_tagged_lines(markup)
    assert len(tagged) == 4
    assert [k for k, _ in tagged] == ["도깨비", "할아버지", "욕심쟁이", "도깨비"]


def test_catalog_stories_no_untagged_standalone_dialogue() -> None:
    for story in list_stories():
        markup = _markup_body(story.path)
        assert_untagged_lines_have_no_standalone_dialogue(markup)
        assert_markup_lines_are_quoted_dialogue(markup)


def main() -> int:
    test_parse_and_strip()
    test_markup_stories_strip_to_canonical_and_tagged_lines_are_quotes()
    test_no_speaker_merge_across_lines()
    test_horangi_wa_gotgam_six_dialogue_lines()
    test_eunhye_gapeun_kkachi_five_dialogue_lines()
    test_geum_dokki_seven_dialogue_chunks()
    test_ui_joeun_hyeongje_three_dialogue_lines()
    test_hokburi_yeonggam_four_dialogue_lines()
    test_catalog_stories_no_untagged_standalone_dialogue()
    print("OK: story speaker markup tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
