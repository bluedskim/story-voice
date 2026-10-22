#!/usr/bin/env python3
"""Dialogue audio post-process tests (ffmpeg, no MLX)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_post import (
    apply_dialogue_style,
    build_dialogue_filter_chain,
    ffmpeg_has_rubberband,
    pitch_filter_expr,
)
from audio_quality_config import DEFAULT_DIALOGUE_GAIN_DB, DEFAULT_DIALOGUE_PITCH_ST


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


def test_pitch_filter_prefers_rubberband_when_available() -> None:
    expr, method = pitch_filter_expr(DEFAULT_DIALOGUE_PITCH_ST, 24000)
    if ffmpeg_has_rubberband():
        assert method == "rubberband"
        assert expr.startswith("rubberband=pitch=")
    else:
        assert method == "asetrate"
        assert "asetrate=" in expr
        assert "atempo=" in expr


def test_dialogue_filter_includes_fades_and_gain() -> None:
    chain, _ = build_dialogue_filter_chain(1.0, 24000)
    assert "afade=t=in" in chain
    assert "afade=t=out" in chain
    assert f"volume={DEFAULT_DIALOGUE_GAIN_DB}dB" in chain


def test_apply_dialogue_style_writes_output() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.wav"
        out = Path(tmp) / "out.wav"
        make_tone_wav(src, 0.4)
        method = apply_dialogue_style(src, out, 24000)
        assert out.is_file()
        assert out.stat().st_size > 0
        assert method in {"rubberband", "asetrate"}


def main() -> int:
    test_pitch_filter_prefers_rubberband_when_available()
    test_dialogue_filter_includes_fades_and_gain()
    test_apply_dialogue_style_writes_output()
    print(f"OK: audio post tests (pitch method on this host: {'rubberband' if ffmpeg_has_rubberband() else 'asetrate'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
