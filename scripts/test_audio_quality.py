#!/usr/bin/env python3
"""Unit tests for chunking, CER, ASR retry policy, and ffmpeg post-process (no MLX)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_post import build_loudnorm_filter, build_trim_silence_filter, ffmpeg_loudnorm_m4a, ffmpeg_trim_chunk
from asr_verify import extract_transcript, should_retry, should_skip_mass_retry
from cer import character_error_rate, normalize_korean_for_cer
from story_chunking import split_story_into_chunks
from story_text import narration_text_from_string


def test_sentence_chunking_korean_quotes() -> None:
    text = (
        '형이 말했어요. "엄마, 눈은 어디서 와요?" 아이가 물었어요.\n'
        "엄마는 빙긋 웃었지요…\n"
        "밤이 깊었어요."
    )
    chunks = split_story_into_chunks(text)
    assert len(chunks) >= 3
    dialogue = [c for c in chunks if c.dialogue]
    assert dialogue, "expected dialogue chunks with quotes"
    assert any("?" in c.text for c in chunks)
    assert chunks[-1].pause_after == "paragraph"


def test_cer_normalization() -> None:
    ref = '"엄마, 눈은 어디서 와요?"'
    hyp = "엄마 눈은 어디서 와요"
    assert normalize_korean_for_cer(ref) == normalize_korean_for_cer(hyp)
    assert character_error_rate(ref, hyp) == 0.0


def test_cer_detects_substitution() -> None:
    cer = character_error_rate("안녕하세요", "안녕하세오")
    assert 0 < cer < 0.5


def test_should_retry_respects_cap() -> None:
    assert should_retry(0.5, 0.18, 1, 3) is True
    assert should_retry(0.5, 0.18, 3, 3) is False
    assert should_retry(0.1, 0.18, 1, 3) is False


def test_ellipsis_sentence_boundary() -> None:
    chunks = split_story_into_chunks("잠이 들었어요…\n\n아침이 밝았어요.")
    assert len(chunks) == 2
    assert "…" in chunks[0].text


def test_frontmatter_not_in_chunks() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        story_file = Path(tmp) / "t.txt"
        story_file.write_text(
            "---\ntitle: 의좋은 형제\nid: ui-joeun-hyeongje\norder: 1\n---\n"
            "옛날 옛적 이야기가 시작되었어요.\n",
            encoding="utf-8",
        )
        from clone_story import read_story_text

        body = read_story_text(story_file)
        chunks = split_story_into_chunks(body)
        joined = " ".join(c.text for c in chunks)
        assert "title:" not in joined
        assert "---" not in joined
        assert "ui-joeun-hyeongje" not in joined
        assert "이야기" in joined


def test_frontmatter_string_helper() -> None:
    raw = "---\nid: x\n---\n본문만 읽어요."
    assert narration_text_from_string(raw) == "본문만 읽어요."


def test_chunk_packing_target_length() -> None:
    text = "첫 문장입니다. " * 3 + "둘째 문장입니다. " * 3 + "마지막 문장입니다."
    chunks = split_story_into_chunks(text)
    assert chunks
    assert all(len(c.text) <= 120 for c in chunks)
    assert any(len(c.text) >= 60 for c in chunks)


def test_extract_transcript_stt_output() -> None:
    class Seg:
        def __init__(self, text: str) -> None:
            self.text = text

    class Out:
        text = ""
        segments = [Seg("안녕"), Seg("하세요")]

    assert extract_transcript(Out()) == "안녕 하세요"

    class Full:
        text = "완전한 문장"

    assert extract_transcript(Full()) == "완전한 문장"

    class Bad:
        def __str__(self) -> str:
            return "STTOutput(text='ignored', prompt_tokens=99999)"

    assert extract_transcript(Bad()) == ""


def test_mass_retry_skip() -> None:
    assert should_skip_mass_retry(16, 29) is True
    assert should_skip_mass_retry(5, 29) is False


def test_retry_keeps_lowest_cer() -> None:
    """Simulate per-chunk best-of-N selection used in ASR retry loop."""
    best_cer = 0.4
    for cer in (0.35, 0.22, 0.25):
        if cer <= best_cer:
            best_cer = cer
    assert best_cer == 0.22


def test_postprocess_command_shape() -> None:
    assert "silenceremove" in build_trim_silence_filter()
    assert "loudnorm" in build_loudnorm_filter()
    cmd = ffmpeg_trim_chunk(Path("in.wav"), Path("out.wav"))
    assert cmd[0] == "ffmpeg" and "-af" in cmd
    m4a = ffmpeg_loudnorm_m4a(Path("story.wav"), Path("story.m4a"))
    assert "aac" in m4a
    assert "-16" in " ".join(m4a) or "loudnorm=I=-16" in build_loudnorm_filter()


def main() -> int:
    test_frontmatter_not_in_chunks()
    test_sentence_chunking_korean_quotes()
    test_cer_normalization()
    test_cer_detects_substitution()
    test_should_retry_respects_cap()
    test_ellipsis_sentence_boundary()
    test_frontmatter_string_helper()
    test_chunk_packing_target_length()
    test_extract_transcript_stt_output()
    test_mass_retry_skip()
    test_retry_keeps_lowest_cer()
    test_postprocess_command_shape()
    print("OK: audio quality unit tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
