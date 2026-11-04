"""Stories tab generation UI: confirm modal, no always-visible ASR checkbox."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

ASR_HINT = (
    "만든 낭독을 음성 인식으로 몇 문장씩 다시 들어 봐요. "
    "대본과 많이 다르게 읽힌 부분은 최대 2번까지 다시 만들어 "
    "가장 정확한 것을 써요. 대신 만드는 시간이 더 걸려요."
)


def stories_panel_html() -> str:
    m = re.search(r'<section id="panel-stories"[^>]*>(.*?)</section>', INDEX, re.S)
    assert m, "panel-stories missing"
    return m.group(1)


def test_stories_tab_has_no_always_visible_asr_checkbox() -> None:
    panel = stories_panel_html()
    assert "regen-asr" not in panel
    assert "asr-help" not in panel
    assert "발음 확인 후 다시 만들기" not in panel


def test_generation_confirm_modal_copy() -> None:
    assert 'id="modal-gen-confirm"' in INDEX
    assert "발음 확인 후 자동 재생성" in INDEX
    assert ASR_HINT in INDEX
    assert "asr-help-btn" not in INDEX
    assert "gen-confirm-submit" in INDEX and "만들기" in INDEX
    assert "gen-confirm-cancel" in INDEX and "취소" in INDEX


def test_app_opens_modal_and_sends_asr_verify() -> None:
    assert "openGenerationConfirm" in APP_JS
    assert "generationRequestBody(asrVerify" in APP_JS
    assert "asrVerify: Boolean(asrVerify)" in APP_JS
    assert "regen-asr-verify" not in APP_JS
    assert "setupAsrHelp" not in APP_JS


def test_generation_progress_on_story_card() -> None:
    assert 'id="gen-progress"' not in INDEX
    assert "genProgressBarEl" not in APP_JS
    assert "story-gen-progress" in APP_JS
    assert "setGenCardProgress" in APP_JS
    assert "syncGenCardProgressUi" in APP_JS
    assert "running.chunkIndex || 0" in APP_JS
    assert "running.chunkTotal || 1" in APP_JS
    assert "genProgressPercent" in APP_JS
    assert "만드는 중:" in APP_JS
    assert "clearGenCardProgress" in APP_JS


if __name__ == "__main__":
    test_stories_tab_has_no_always_visible_asr_checkbox()
    test_generation_confirm_modal_copy()
    test_app_opens_modal_and_sends_asr_verify()
    test_generation_progress_on_story_card()
    print("ok")
