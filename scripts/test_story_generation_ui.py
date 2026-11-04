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


def test_generation_done_updates_story_card_in_place() -> None:
    assert "patchStoryCardInPlace" in APP_JS
    assert "applyGenerationDone" in APP_JS
    assert "storyIdsFromRecentJob" in APP_JS
    done_block = re.search(
        r'if \(last\?\.state === "done"\)\s*\{(.+?)\n  \}',
        APP_JS,
        re.S,
    )
    assert done_block, "pollGeneration done branch missing"
    body = done_block.group(1)
    assert "await applyGenerationDone(last)" in body
    assert "await loadCatalog()" not in body
    assert "loadCatalog({ showLoading: false })" in APP_JS
    assert "showGenerationCompleteFeedback(storyIds)" in body


def test_generation_done_completion_notice() -> None:
    assert 'id="gen-complete-toast"' in INDEX
    assert "gen-complete-toast" in (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
    assert "showGenerationCompleteFeedback" in APP_JS
    assert "mountStoryGenComplete" in APP_JS
    assert "showGenCompleteToast" in APP_JS
    assert "✓ 완성됐어요" in APP_JS
    assert "is-gen-complete" in APP_JS
    assert "이야기가 완성됐어요" in APP_JS
    assert "들어보기" in INDEX
    assert "playStoryFromCard" in APP_JS
    assert "scrollIntoView" in APP_JS
    done_block = re.search(
        r'if \(last\?\.state === "done"\)\s*\{(.+?)\n  \}',
        APP_JS,
        re.S,
    )
    assert done_block
    assert "새 목소리로 만들었어요" not in done_block.group(1)


def test_story_card_status_copy() -> None:
    personal_branch = re.search(
        r'if \(story\.audioSource === "personal"\)\s*\{[^}]+\}',
        APP_JS,
    )
    assert personal_branch, "storyStatusMessage personal branch missing"
    assert "내 목소리로 재생할 준비됐어요" not in APP_JS
    assert 'return ""' in personal_branch.group(0)
    assert "기본 낭독을 준비하는 중이에요" in APP_JS
    assert "기본 낭독으로 들을 수 있어요" in APP_JS
    assert "applyStoryStatus" in APP_JS
    assert "restoreStoryStatus" in APP_JS
    assert 'setStatus(card, "재생 중…")' not in APP_JS
    assert 'setStatus(card, "일시정지")' not in APP_JS
    assert 'setStatus(card, "끝났어요.")' not in APP_JS
    assert "불러오는 중…" in APP_JS
    assert "재생할 수 없어요" in APP_JS


def test_story_card_has_no_download_button() -> None:
    assert "다운로드" not in APP_JS
    assert "?download=1" not in APP_JS
    assert "내 목소리로 다시 만들기" in APP_JS
    assert "내 목소리로 만들기" in APP_JS


def test_generation_polling_resumes_while_job_active() -> None:
    assert re.search(r"loadCatalog\(\);\s*\nstartPolling\(\);", APP_JS)
    assert re.search(
        r"loadCatalog\(\);\s*\npollGeneration\(\);",
        APP_JS,
    ) is None
    poll_body = re.search(
        r"async function pollGeneration\(\)\s*\{(.+?)}\n\nfunction ensureGenerationPolling",
        APP_JS,
        re.S,
    )
    assert poll_body, "pollGeneration block missing"
    body = poll_body.group(1)
    running = re.search(r"if \(running\)\s*\{(.+?)\n  \}", body, re.S)
    assert running and "ensureGenerationPolling()" in running.group(1)
    queued = re.search(r"if \(data\.queued\?\.length\)\s*\{(.+?)\n  \}", body, re.S)
    assert queued and "ensureGenerationPolling()" in queued.group(1)
    assert "function ensureGenerationPolling()" in APP_JS
    assert "visibilitychange" in APP_JS
    assert "resumeGenerationPollingOnVisible" in APP_JS
    assert "lastHandledGenerationJobId" in APP_JS
    done_block = re.search(
        r'if \(last\?\.state === "done"\)\s*\{(.+?)\n  \}',
        body,
        re.S,
    )
    assert done_block
    assert "generationJobWasObserved" in done_block.group(1)
    assert "lastHandledGenerationJobId" in done_block.group(1)


def test_generation_completion_only_if_job_was_observed_active() -> None:
    assert "observedGenerationJobIds" in APP_JS
    assert "markGenerationJobObserved" in APP_JS
    assert "generationJobWasObserved" in APP_JS
    poll_body = re.search(
        r"async function pollGeneration\(\)\s*\{(.+?)}\n\nfunction ensureGenerationPolling",
        APP_JS,
        re.S,
    )
    assert poll_body
    body = poll_body.group(1)
    running = re.search(r"if \(running\)\s*\{(.+?)\n  \}", body, re.S)
    assert running and "markGenerationJobObserved(running)" in running.group(1)
    queued = re.search(r"if \(data\.queued\?\.length\)\s*\{(.+?)\n  \}", body, re.S)
    assert queued and "markGenerationJobObserved(job)" in queued.group(1)
    done = re.search(r'if \(last\?\.state === "done"\)\s*\{(.+?)\n  \}', body, re.S)
    assert done
    done_body = done.group(1)
    assert re.search(
        r"if \(observed\)\s*\{[^}]*applyGenerationDone",
        done_body,
        re.S,
    )
    assert "showGenerationCompleteFeedback" in done_body
    failed = re.search(r'if \(last\?\.state === "failed"\)\s*\{(.+?)\n  \}', body, re.S)
    assert failed
    assert "generationJobWasObserved(last.jobId)" in failed.group(1)
    assert "markGenerationJobObserved(data.job)" in APP_JS


if __name__ == "__main__":
    test_stories_tab_has_no_always_visible_asr_checkbox()
    test_generation_confirm_modal_copy()
    test_app_opens_modal_and_sends_asr_verify()
    test_generation_progress_on_story_card()
    test_generation_done_updates_story_card_in_place()
    test_generation_done_completion_notice()
    test_story_card_status_copy()
    test_story_card_has_no_download_button()
    test_generation_polling_resumes_while_job_active()
    test_generation_completion_only_if_job_was_observed_active()
    print("ok")
