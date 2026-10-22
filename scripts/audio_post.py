"""ffmpeg helpers for dialogue chunk post-processing."""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

from audio_quality_config import (
    dialogue_fade_sec,
    dialogue_gain_db,
    dialogue_pitch_semitones,
    narration_loudnorm_enabled,
    narration_loudnorm_integrated,
)

PitchMethod = str  # "rubberband" | "asetrate"


@lru_cache(maxsize=1)
def ffmpeg_has_rubberband() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            check=False,
        )
        return "rubberband" in (result.stdout or "")
    except OSError:
        return False


def pitch_scale_from_semitones(semitones: float) -> float:
    return 2.0 ** (semitones / 12.0)


def pitch_filter_expr(semitones: float, sample_rate: int) -> tuple[str, PitchMethod]:
    scale = pitch_scale_from_semitones(semitones)
    if ffmpeg_has_rubberband():
        return f"rubberband=pitch={scale:.8f}", "rubberband"
    new_rate = max(8000, int(round(sample_rate * scale)))
    inv = 1.0 / scale
    # asetrate shifts pitch+duration; atempo restores duration (pitch stays shifted).
    return f"asetrate={new_rate},aresample={sample_rate},atempo={inv:.8f}", "asetrate"


def probe_duration_sec(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def build_dialogue_filter_chain(duration_sec: float, sample_rate: int) -> tuple[str, PitchMethod]:
    fade = dialogue_fade_sec()
    gain = dialogue_gain_db()
    pitch_st = dialogue_pitch_semitones()
    pitch_af, method = pitch_filter_expr(pitch_st, sample_rate)
    fade_out_start = max(0.0, duration_sec - fade)
    parts = [
        f"afade=t=in:st=0:d={fade:.4f}",
        pitch_af,
        f"volume={gain}dB",
        f"afade=t=out:st={fade_out_start:.4f}:d={fade:.4f}",
    ]
    return ",".join(parts), method


def ffmpeg_dialogue_style_cmd(input_wav: Path, output_wav: Path, sample_rate: int = 24000) -> tuple[list[str], PitchMethod]:
    duration = probe_duration_sec(input_wav)
    filter_str, method = build_dialogue_filter_chain(duration, sample_rate)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(input_wav),
        "-af",
        filter_str,
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        str(output_wav),
    ]
    return cmd, method


def ffmpeg_narration_loudnorm_cmd(input_wav: Path, output_wav: Path, sample_rate: int = 24000) -> list[str]:
    i = narration_loudnorm_integrated()
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(input_wav),
        "-af",
        f"loudnorm=I={i}:TP=-1.5:LRA=11:print_format=none",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        str(output_wav),
    ]


def run_ffmpeg(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def apply_dialogue_style(input_wav: Path, output_wav: Path, sample_rate: int = 24000) -> PitchMethod:
    cmd, method = ffmpeg_dialogue_style_cmd(input_wav, output_wav, sample_rate)
    run_ffmpeg(cmd)
    return method


def apply_narration_loudnorm_if_enabled(input_wav: Path, sample_rate: int = 24000) -> None:
    if not narration_loudnorm_enabled():
        return
    styled = input_wav.with_suffix(".loudnorm.wav")
    run_ffmpeg(ffmpeg_narration_loudnorm_cmd(input_wav, styled, sample_rate))
    styled.replace(input_wav)
