"""ffmpeg helpers for dialogue chunk post-processing."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from audio_quality_config import (
    dialogue_eq_filter,
    dialogue_fade_sec,
    dialogue_gain_db,
    dialogue_pitch_semitones,
    dialogue_post_should_run,
    narration_loudnorm_enabled,
    narration_loudnorm_integrated,
)

PitchMethod = str  # "rubberband" | "asetrate" | "none"
MeanDbMethod = str  # "volumedetect" | "numpy"

_VOLUMEDETECT_RE = re.compile(r"mean_volume:\s*([-\d.]+)\s*dB")


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


def volumedetect_mean_db(path: Path) -> float:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    match = _VOLUMEDETECT_RE.search(result.stderr or "")
    if not match:
        return wav_rms_mean_db(path)
    return float(match.group(1))


def wav_rms_mean_db(path: Path) -> float:
    import numpy as np

    result = subprocess.run(
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
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    if samples.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(samples * samples)))
    if rms <= 1e-12:
        return -120.0
    return 20.0 * float(np.log10(rms))


def build_dialogue_middle_chain(sample_rate: int) -> tuple[str, PitchMethod]:
    """Fade-in plus optional pitch, gain, and EQ (no fade-out, no loudness match)."""
    fade = dialogue_fade_sec()
    parts: list[str] = [f"afade=t=in:st=0:d={fade:.4f}"]
    pitch_method: PitchMethod = "none"
    pitch_st = dialogue_pitch_semitones()
    if abs(pitch_st) > 1e-9:
        pitch_af, pitch_method = pitch_filter_expr(pitch_st, sample_rate)
        parts.append(pitch_af)
    gain = dialogue_gain_db()
    if abs(gain) > 1e-9:
        parts.append(f"volume={gain}dB")
    eq = dialogue_eq_filter()
    if eq:
        parts.append(eq)
    return ",".join(parts), pitch_method


def build_dialogue_filter_chain(duration_sec: float, sample_rate: int) -> tuple[str, PitchMethod]:
    """Full chain for tests (middle + placeholder volume + fade-out)."""
    middle, method = build_dialogue_middle_chain(sample_rate)
    fade = dialogue_fade_sec()
    fade_out_start = max(0.0, duration_sec - fade)
    return f"{middle},volume=0dB,afade=t=out:st={fade_out_start:.4f}:d={fade:.4f}", method


def ffmpeg_run_af(input_wav: Path, output_wav: Path, af_chain: str, sample_rate: int) -> None:
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(input_wav),
            "-af",
            af_chain,
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            str(output_wav),
        ]
    )


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


def apply_dialogue_style(input_wav: Path, output_wav: Path, sample_rate: int = 24000) -> str:
    """EQ-focused dialogue styling with loudness match to pre-process mean level."""
    if not dialogue_post_should_run():
        return "none"

    mean_in = volumedetect_mean_db(input_wav)
    duration = probe_duration_sec(input_wav)
    fade = dialogue_fade_sec()
    fade_out_start = max(0.0, duration - fade)
    middle_af, pitch_method = build_dialogue_middle_chain(sample_rate)

    with tempfile.TemporaryDirectory(prefix="dialogue_af_") as tmp:
        mid = Path(tmp) / "mid.wav"
        ffmpeg_run_af(input_wav, mid, middle_af, sample_rate)
        mean_mid = volumedetect_mean_db(mid)
        correction_db = mean_in - mean_mid
        tail = f"volume={correction_db:.4f}dB,afade=t=out:st={fade_out_start:.4f}:d={fade:.4f}"
        ffmpeg_run_af(mid, output_wav, tail, sample_rate)

    if dialogue_eq_filter():
        return f"eq+{pitch_method}" if pitch_method != "none" else "eq"
    return pitch_method


def apply_narration_loudnorm_if_enabled(input_wav: Path, sample_rate: int = 24000) -> None:
    if not narration_loudnorm_enabled():
        return
    styled = input_wav.with_suffix(".loudnorm.wav")
    run_ffmpeg(ffmpeg_narration_loudnorm_cmd(input_wav, styled, sample_rate))
    styled.replace(input_wav)
