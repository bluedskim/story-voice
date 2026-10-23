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
    apply_dialogue_style,
    build_dialogue_middle_chain,
    build_dialogue_tail_filter,
    volumedetect_mean_db,
)
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


def test_defaults_use_airy_preset() -> None:
    _clear_dialogue_env()
    assert DEFAULT_DIALOGUE_PITCH_ST == 0.0
    assert DEFAULT_DIALOGUE_GAIN_DB == 0.0
    assert DEFAULT_DIALOGUE_EQ_PRESET == "airy"
    eq = dialogue_eq_filter()
    assert eq == DIALOGUE_EQ_PRESETS["airy"]
    assert "highpass=f=110" in eq
    assert dialogue_post_should_run()


def test_disable_dialogue_style() -> None:
    _clear_dialogue_env()
    os.environ["STORY_VOICE_DIALOGUE_STYLE"] = "0"
    try:
        assert not dialogue_post_should_run()
    finally:
        os.environ.pop("STORY_VOICE_DIALOGUE_STYLE", None)


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


def test_tail_includes_limiter_before_fade() -> None:
    tail = build_dialogue_tail_filter(3.0, 0.4, 0.012)
    assert DIALOGUE_PEAK_LIMITER in tail
    assert tail.index(DIALOGUE_PEAK_LIMITER) < tail.index("afade=t=out")


def test_apply_eq_loudness_match() -> None:
    _clear_dialogue_env()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.wav"
        out = Path(tmp) / "out.wav"
        make_tone_wav(src, 0.5)
        mean_in = volumedetect_mean_db(src)
        mode = apply_dialogue_style(src, out, 24000)
        assert mode.startswith("eq")
        mean_out = volumedetect_mean_db(out)
        assert abs(mean_out - mean_in) < 1.5


def main() -> int:
    test_defaults_use_airy_preset()
    test_disable_dialogue_style()
    test_bright_preset_override()
    test_tail_includes_limiter_before_fade()
    test_apply_eq_loudness_match()
    print("OK: audio post tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
