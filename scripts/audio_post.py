"""ffmpeg post-processing helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from audio_quality_config import LOUDNORM_I_LUFS, TRIM_SILENCE_THRESHOLD_DB


def build_trim_silence_filter() -> str:
    th = TRIM_SILENCE_THRESHOLD_DB
    return (
        f"silenceremove=start_periods=1:start_silence=0.05:start_threshold={th}dB:detection=peak,"
        "areverse,"
        f"silenceremove=start_periods=1:start_silence=0.05:start_threshold={th}dB:detection=peak,"
        "areverse"
    )


def ffmpeg_trim_chunk(in_wav: Path, out_wav: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(in_wav),
        "-af",
        build_trim_silence_filter(),
        str(out_wav),
    ]


def ffmpeg_concat_wav(list_path: Path, out_wav: Path, sample_rate: int) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]


def build_loudnorm_filter() -> str:
    return f"loudnorm=I={LOUDNORM_I_LUFS}:TP=-1.5:LRA=11"


def ffmpeg_loudnorm_m4a(in_wav: Path, out_m4a: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(in_wav),
        "-af",
        build_loudnorm_filter(),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out_m4a),
    ]


def run_ffmpeg(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)
