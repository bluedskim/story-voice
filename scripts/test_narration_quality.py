#!/usr/bin/env python3
"""Loudnorm + ASR verify policy tests (no MLX)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from asr_verify import FakeAsrTranscriber, should_skip_mass_retry, score_chunk
from audio_quality_config import asr_verify_enabled, final_loudnorm_enabled, parse_asr_verify_body, resolve_asr_verify
from audio_post import apply_final_loudnorm_if_enabled, loudnorm_two_pass_wav
from cer import character_error_rate


def test_resolve_asr_verify_precedence() -> None:
    env = os.environ.copy()
    old = os.environ.get("STORY_VOICE_ASR_VERIFY")
    try:
        os.environ["STORY_VOICE_ASR_VERIFY"] = "1"
        assert resolve_asr_verify(None) is True
        assert resolve_asr_verify(False) is False
        assert resolve_asr_verify(True) is True
        assert parse_asr_verify_body({}) is None
        assert parse_asr_verify_body({"asrVerify": False}) is False
        try:
            parse_asr_verify_body({"asrVerify": "yes"})
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    finally:
        if old is None:
            os.environ.pop("STORY_VOICE_ASR_VERIFY", None)
        else:
            os.environ["STORY_VOICE_ASR_VERIFY"] = old


def test_asr_verify_default_off() -> None:
    env = os.environ.copy()
    env.pop("STORY_VOICE_ASR_VERIFY", None)
    old = os.environ.get("STORY_VOICE_ASR_VERIFY")
    try:
        if "STORY_VOICE_ASR_VERIFY" in os.environ:
            del os.environ["STORY_VOICE_ASR_VERIFY"]
        assert asr_verify_enabled() is False
    finally:
        if old is not None:
            os.environ["STORY_VOICE_ASR_VERIFY"] = old


def test_final_loudnorm_default_on() -> None:
    old = os.environ.pop("STORY_VOICE_LOUDNORM", None)
    try:
        assert final_loudnorm_enabled() is True
    finally:
        if old is not None:
            os.environ["STORY_VOICE_LOUDNORM"] = old


def test_mass_retry_skip() -> None:
    assert should_skip_mass_retry(3, 4) is True
    assert should_skip_mass_retry(1, 4) is False


def test_cer_and_fake_asr() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "t.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.2",
                "-ar",
                "24000",
                str(wav),
            ],
            check=True,
        )
        cer, _ = score_chunk(FakeAsrTranscriber(), wav, "안녕")
        assert cer == 1.0
        cer0, _ = score_chunk(FakeAsrTranscriber("안녕"), wav, "안녕")
        assert cer0 == 0.0
    assert character_error_rate("abc", "abc") == 0.0


def test_loudnorm_two_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.wav"
        out = Path(tmp) / "out.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=220:duration=1.0",
                "-ar",
                "24000",
                str(src),
            ],
            check=True,
        )
        loudnorm_two_pass_wav(src, out, -16.0)
        assert out.is_file() and out.stat().st_size > 1000
        os.environ["STORY_VOICE_LOUDNORM"] = "1"
        apply_final_loudnorm_if_enabled(src)
        assert src.is_file()


def main() -> int:
    test_resolve_asr_verify_precedence()
    test_asr_verify_default_off()
    test_final_loudnorm_default_on()
    test_mass_retry_skip()
    test_cer_and_fake_asr()
    test_loudnorm_two_pass()
    print("OK: narration quality tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
