#!/usr/bin/env python3
"""Dialogue audio post-process tests (ffmpeg, no MLX)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_post import (
    _parse_loudnorm_json,
    apply_chunk_tail_pad,
    apply_dialogue_style,
    apply_final_loudnorm_if_enabled,
    build_dialogue_middle_chain,
    build_dialogue_tail_filter,
    probe_duration_sec,
    volumedetect_mean_db,
)
from audio_quality_config import DEFAULT_CHUNK_TAIL_PAD_SEC, chunk_tail_pad_sec
from audio_quality_config import (
    DEFAULT_DIALOGUE_EQ_PRESET,
    DEFAULT_DIALOGUE_GAIN_DB,
    DEFAULT_DIALOGUE_PITCH_ST,
    DIALOGUE_EQ_PRESETS,
    DIALOGUE_PEAK_LIMITER,
    dialogue_eq_filter,
    dialogue_post_should_run,
)


def make_tone_wav(path: Path, duration: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-ar",
            "24000",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
    )


def _clear_dialogue_env() -> None:
    for key in (
        "STORY_VOICE_DIALOGUE_EQ",
        "STORY_VOICE_DIALOGUE_EQ_PRESET",
        "STORY_VOICE_DIALOGUE_STYLE",
    ):
        os.environ.pop(key, None)


def test_defaults_dialogue_post_off() -> None:
    _clear_dialogue_env()
    assert DEFAULT_DIALOGUE_PITCH_ST == 0.0
    assert DEFAULT_DIALOGUE_GAIN_DB == 0.0
    assert DEFAULT_DIALOGUE_EQ_PRESET == "airy"
    assert not dialogue_post_should_run()
    eq = dialogue_eq_filter()
    assert eq == DIALOGUE_EQ_PRESETS["airy"]


def test_enable_dialogue_style_runs_airy_eq() -> None:
    _clear_dialogue_env()
    os.environ["STORY_VOICE_DIALOGUE_STYLE"] = "1"
    try:
        assert dialogue_post_should_run()
        eq = dialogue_eq_filter()
        assert eq and "highpass=f=110" in eq
    finally:
        os.environ.pop("STORY_VOICE_DIALOGUE_STYLE", None)


def test_disable_dialogue_style() -> None:
    _clear_dialogue_env()
    os.environ["STORY_VOICE_DIALOGUE_STYLE"] = "0"
    try:
        assert not dialogue_post_should_run()
    finally:
        os.environ.pop("STORY_VOICE_DIALOGUE_STYLE", None)


def test_dialogue_eq_zero_disables_filter() -> None:
    _clear_dialogue_env()
    os.environ["STORY_VOICE_DIALOGUE_STYLE"] = "1"
    os.environ["STORY_VOICE_DIALOGUE_EQ"] = "0"
    try:
        assert dialogue_eq_filter() is None
        assert not dialogue_post_should_run()
    finally:
        os.environ.pop("STORY_VOICE_DIALOGUE_STYLE", None)
        os.environ.pop("STORY_VOICE_DIALOGUE_EQ", None)


def test_bright_preset_override() -> None:
    _clear_dialogue_env()
    os.environ["STORY_VOICE_DIALOGUE_EQ_PRESET"] = "bright"
    try:
        eq = dialogue_eq_filter()
        assert eq and "highpass=f=90" in eq
        chain, _ = build_dialogue_middle_chain(24000)
        assert "highpass=f=90" in chain
        assert "afade=t=in" in chain
    finally:
        os.environ.pop("STORY_VOICE_DIALOGUE_EQ_PRESET", None)


def test_tail_has_limiter_without_fade_out() -> None:
    tail = build_dialogue_tail_filter(3.0)
    assert DIALOGUE_PEAK_LIMITER in tail
    assert "afade=t=out" not in tail


def test_chunk_tail_pad_extends_duration() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.wav"
        make_tone_wav(src, 0.2)
        before = probe_duration_sec(src)
        apply_chunk_tail_pad(src, 24000)
        after = probe_duration_sec(src)
        assert after - before >= chunk_tail_pad_sec() - 0.002


def test_dialogue_style_preserves_speech_tail_energy() -> None:
    """Regression: fade-out on the last 12ms used to eat quiet word endings."""
    import numpy as np

    def tail_rms(path: Path, ms: float = 15.0) -> float:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-f",
                "f32le",
                "-ac",
                "1",
                "-",
            ],
            capture_output=True,
            check=True,
        )
        samples = np.frombuffer(proc.stdout, dtype=np.float32)
        n = int(24000 * ms / 1000.0)
        tail = samples[-n:] if samples.size >= n else samples
        return float(np.sqrt(np.mean(tail * tail)))

    _clear_dialogue_env()
    os.environ["STORY_VOICE_DIALOGUE_STYLE"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.wav"
            out = Path(tmp) / "out.wav"
            make_tone_wav(src, 0.12)
            in_tail = tail_rms(src)
            apply_dialogue_style(src, out, 24000)
            out_tail = tail_rms(out)
            assert out_tail >= in_tail * 0.75
    finally:
        os.environ.pop("STORY_VOICE_DIALOGUE_STYLE", None)


FFMPEG9_LOUDNORM_STDERR = """[Parsed_loudnorm_0 @ 0xaaaabbbb] 
{
    "input_i" : "-20.64",
    "input_tp" : "-1.23",
    "input_lra" : "0.00",
    "input_thresh" : "-30.64",
    "output_i" : "-16.00",
    "output_tp" : "-1.50",
    "output_lra" : "0.00",
    "output_thresh" : "-26.05",
    "normalization_type" : "linear",
    "target_offset" : "0.05"
}
[out#0/null @ 0xccccdddd] 
muxing overhead: unknown
size=       0KiB time=00:00:01.00 bitrate=   0.0kbits/s speed= 100x    
"""


def test_parse_loudnorm_json_ffmpeg9_trailing_lines() -> None:
    stats = _parse_loudnorm_json(FFMPEG9_LOUDNORM_STDERR)
    assert stats["input_i"] == "-20.64"
    assert stats["target_offset"] == "0.05"


def test_parse_loudnorm_json_brace_noise_before() -> None:
    stderr = (
        "[ffmpeg] unrelated {brace: noise} in log line\n"
        + FFMPEG9_LOUDNORM_STDERR
    )
    stats = _parse_loudnorm_json(stderr)
    assert stats["input_i"] == "-20.64"


def test_loudnorm_fallback_keeps_input_on_failure() -> None:
    from unittest import mock

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "story.wav"
        make_tone_wav(src, 0.3)
        before = src.read_bytes()
        os.environ["STORY_VOICE_LOUDNORM"] = "1"
        with mock.patch(
            "audio_post.loudnorm_two_pass_wav",
            side_effect=RuntimeError("simulated loudnorm failure"),
        ):
            result = apply_final_loudnorm_if_enabled(src)
        assert result == src
        assert src.read_bytes() == before


def test_apply_eq_loudness_match() -> None:
    _clear_dialogue_env()
    os.environ["STORY_VOICE_DIALOGUE_STYLE"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.wav"
            out = Path(tmp) / "out.wav"
            make_tone_wav(src, 0.5)
            mean_in = volumedetect_mean_db(src)
            mode = apply_dialogue_style(src, out, 24000)
            assert mode.startswith("eq")
            mean_out = volumedetect_mean_db(out)
            assert abs(mean_out - mean_in) < 1.5
    finally:
        os.environ.pop("STORY_VOICE_DIALOGUE_STYLE", None)


def main() -> int:
    test_defaults_dialogue_post_off()
    test_enable_dialogue_style_runs_airy_eq()
    test_disable_dialogue_style()
    test_dialogue_eq_zero_disables_filter()
    test_bright_preset_override()
    assert DEFAULT_CHUNK_TAIL_PAD_SEC > 0
    test_tail_has_limiter_without_fade_out()
    test_chunk_tail_pad_extends_duration()
    test_dialogue_style_preserves_speech_tail_energy()
    test_parse_loudnorm_json_ffmpeg9_trailing_lines()
    test_parse_loudnorm_json_brace_noise_before()
    test_loudnorm_fallback_keeps_input_on_failure()
    test_apply_eq_loudness_match()
    print("OK: audio post tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
