"""ffmpeg helpers for dialogue chunk post-processing."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from audio_quality_config import (
    DIALOGUE_PEAK_LIMITER,
    chunk_lead_fade_sec,
    chunk_lead_strip_enabled,
    chunk_tail_guard_enabled,
    chunk_tail_guard_extra_sec,
    chunk_tail_guard_min_silence_sec,
    chunk_tail_pad_sec,
    dialogue_eq_filter,
    dialogue_fade_sec,
    dialogue_gain_db,
    dialogue_pitch_semitones,
    dialogue_post_should_run,
    final_loudnorm_enabled,
    final_loudnorm_integrated,
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


def build_dialogue_tail_filter(correction_db: float) -> str:
    """Loudness correction + peak limit (no fade-out; tail pad preserves word endings)."""
    return f"volume={correction_db:.4f}dB,{DIALOGUE_PEAK_LIMITER}"


def build_dialogue_filter_chain(duration_sec: float, sample_rate: int) -> tuple[str, PitchMethod]:
    """Full chain for tests (middle + placeholder volume + limiter)."""
    middle, method = build_dialogue_middle_chain(sample_rate)
    tail = build_dialogue_tail_filter(0.0)
    return f"{middle},{tail}", method


def load_mono_float_samples(path: Path) -> "np.ndarray":
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
    return np.frombuffer(result.stdout, dtype=np.float32)


def trailing_silence_sec(samples: "np.ndarray", sample_rate: int, threshold_ratio: float = 0.02) -> float:
    """Seconds of sub-threshold audio after the last sample above ``threshold_ratio * peak``."""
    import numpy as np

    if samples.size == 0:
        return 0.0
    peak = float(np.max(np.abs(samples)))
    if peak < 1e-8:
        return float(samples.size) / sample_rate
    thresh = peak * threshold_ratio
    last_speech = 0
    for i in range(samples.size - 1, -1, -1):
        if abs(samples[i]) >= thresh:
            last_speech = i
            break
    tail_samples = samples.size - 1 - last_speech
    return max(0.0, tail_samples / sample_rate)


def compute_chunk_tail_pad_sec(input_wav: Path, sample_rate: int = 24000) -> float:
    """Baseline pad plus optional extra when TTS left little natural trailing silence."""
    pad = chunk_tail_pad_sec()
    if not chunk_tail_guard_enabled():
        return pad
    extra = chunk_tail_guard_extra_sec()
    if extra <= 1e-6:
        return pad
    try:
        samples = load_mono_float_samples(input_wav)
        trailing = trailing_silence_sec(samples, sample_rate)
        if trailing < chunk_tail_guard_min_silence_sec():
            pad += extra
    except (OSError, subprocess.CalledProcessError):
        pad += extra
    return pad


def speech_onset_sample(
    samples: "np.ndarray",
    sample_rate: int,
    frame_ms: float = 10.0,
    hold_ms: float = 70.0,
    rel_thresh: float = 0.12,
    abs_floor: float = 0.008,
) -> int:
    """First sample index of sustained speech (skips isolated leading glitches)."""
    import numpy as np

    if samples.size == 0:
        return 0
    frame = max(1, int(sample_rate * frame_ms / 1000.0))
    hold_frames = max(1, int(hold_ms / frame_ms))
    peak = float(np.max(np.abs(samples)))
    if peak < 1e-8:
        return 0
    thresh = max(abs_floor, peak * rel_thresh)
    n_frames = (samples.size + frame - 1) // frame
    consec = 0
    for fi in range(n_frames):
        start = fi * frame
        end = min(samples.size, start + frame)
        rms = float(np.sqrt(np.mean(samples[start:end] ** 2)))
        if rms >= thresh:
            consec += 1
            if consec >= hold_frames:
                return max(0, (fi - hold_frames + 1) * frame)
        else:
            consec = 0
    return 0


def _write_mono_wav(path: Path, samples: "np.ndarray", sample_rate: int) -> None:
    import numpy as np
    import wave

    clipped = np.clip(samples, -1.0, 1.0)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes((clipped * 32767.0).astype(np.int16).tobytes())


def leading_glitch_mute_range(
    samples: "np.ndarray",
    onset: int,
    sample_rate: int,
    max_impulse_ms: float = 30.0,
    min_gap_ms: float = 15.0,
    rel_thresh: float = 0.12,
    abs_floor: float = 0.008,
) -> tuple[int, int]:
    """Sample range [start, end) to zero: short impulse + gap before sustained speech at ``onset``."""
    if onset <= 0:
        return (0, 0)
    import numpy as np

    peak = float(np.max(np.abs(samples)))
    if peak < 1e-8:
        return (0, 0)
    thresh = max(abs_floor, peak * rel_thresh)
    max_impulse = max(1, int(sample_rate * max_impulse_ms / 1000.0))
    min_gap = max(1, int(sample_rate * min_gap_ms / 1000.0))

    gap_end = onset
    i = onset - 1
    while i >= 0 and abs(float(samples[i])) < thresh:
        i -= 1
    gap_start = i + 1
    if gap_end - gap_start < min_gap:
        return (0, 0)

    imp_end = gap_start
    j = imp_end - 1
    while j >= 0 and abs(float(samples[j])) >= thresh:
        j -= 1
    imp_start = j + 1
    imp_len = imp_end - imp_start
    if imp_len <= 0 or imp_len > max_impulse:
        return (0, 0)

    k = imp_start - 1
    while k >= 0 and abs(float(samples[k])) < thresh:
        k -= 1
    if k >= 0:
        return (0, 0)

    return (imp_start, gap_end)


def strip_leading_glitches_before_speech(input_wav: Path, sample_rate: int = 24000) -> int:
    """Mute isolated short leading impulses before sustained speech; returns samples cleared."""
    if not chunk_lead_strip_enabled():
        return 0
    samples = load_mono_float_samples(input_wav).copy()
    onset = speech_onset_sample(samples, sample_rate)
    start, end = leading_glitch_mute_range(samples, onset, sample_rate)
    if end <= start:
        return 0
    samples[start:end] = 0.0
    _write_mono_wav(input_wav, samples, sample_rate)
    return end - start


def apply_chunk_lead_fade_in(input_wav: Path, sample_rate: int = 24000, fade_sec: float | None = None) -> None:
    """Strip isolated leading clicks then fade-in at speech onset before hard concat."""
    samples = load_mono_float_samples(input_wav)
    onset = speech_onset_sample(samples, sample_rate)
    fade_start = 0
    if chunk_lead_strip_enabled():
        start, end = leading_glitch_mute_range(samples, onset, sample_rate)
        if end > start:
            cleared = samples.copy()
            cleared[start:end] = 0.0
            _write_mono_wav(input_wav, cleared, sample_rate)
            fade_start = onset
    fade = fade_sec if fade_sec is not None else chunk_lead_fade_sec()
    if fade <= 1e-6:
        return
    st = fade_start / float(sample_rate)
    faded = input_wav.with_suffix(".leadfade.wav")
    ffmpeg_run_af(input_wav, faded, f"afade=t=in:st={st:.6f}:d={fade:.4f}", sample_rate)
    faded.replace(input_wav)


def apply_chunk_tail_pad(input_wav: Path, sample_rate: int = 24000) -> None:
    """Append silence after chunk post-process (narration + dialogue) before concat."""
    pad = compute_chunk_tail_pad_sec(input_wav, sample_rate)
    if pad <= 1e-6:
        return
    padded = input_wav.with_suffix(".padded.wav")
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(input_wav),
            "-af",
            f"apad=pad_dur={pad:.4f}",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            str(padded),
        ]
    )
    padded.replace(input_wav)


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
    middle_af, pitch_method = build_dialogue_middle_chain(sample_rate)

    with tempfile.TemporaryDirectory(prefix="dialogue_af_") as tmp:
        mid = Path(tmp) / "mid.wav"
        ffmpeg_run_af(input_wav, mid, middle_af, sample_rate)
        mean_mid = volumedetect_mean_db(mid)
        correction_db = mean_in - mean_mid
        tail = build_dialogue_tail_filter(correction_db)
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


def _parse_loudnorm_json(stderr: str) -> dict[str, str]:
    key = stderr.rfind('"input_i"')
    start = stderr.rfind("{", 0, key) if key >= 0 else -1
    if start < 0:
        raise RuntimeError("loudnorm pass1: no JSON in ffmpeg output")
    obj, _end = json.JSONDecoder().raw_decode(stderr[start:])
    return obj


def loudnorm_two_pass_wav(input_wav: Path, output_wav: Path, integrated_lufs: float) -> None:
    """EBU R128 loudnorm (measure pass + apply pass)."""
    base = f"I={integrated_lufs}:TP=-1.5:LRA=11"
    pass1 = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(input_wav),
            "-af",
            f"loudnorm={base}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if pass1.returncode != 0:
        raise RuntimeError(pass1.stderr or "loudnorm pass1 failed")
    stats = _parse_loudnorm_json(pass1.stderr)
    measured = (
        f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}"
    )
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(input_wav),
            "-af",
            f"loudnorm={base}:{measured}:linear=true:print_format=none",
            "-ar",
            "24000",
            "-ac",
            "1",
            str(output_wav),
        ]
    )


def apply_final_loudnorm_if_enabled(input_wav: Path, output_wav: Path | None = None) -> Path:
    """Normalize full story WAV in-place (or to ``output_wav``)."""
    if not final_loudnorm_enabled():
        if output_wav and output_wav != input_wav:
            import shutil

            shutil.copy2(input_wav, output_wav)
        return input_wav
    in_place = output_wav is None
    target = output_wav or input_wav.with_suffix(".normalized.wav")
    try:
        loudnorm_two_pass_wav(input_wav, target, final_loudnorm_integrated())
    except Exception as exc:
        print(
            f"WARNING: story loudnorm failed ({exc}); using un-normalized audio",
            file=sys.stderr,
        )
        if not in_place and target != input_wav:
            import shutil

            shutil.copy2(input_wav, target)
        return input_wav if in_place else target
    if in_place:
        target.replace(input_wav)
        return input_wav
    return target


def encode_story_from_wav(story_wav: Path, out_path: Path, sample_rate: int) -> None:
    """Encode normalized WAV to m4a/mp3/wav destination."""
    suffix = out_path.suffix.lower()
    if suffix in {".m4a", ".mp4"}:
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(story_wav),
                "-ar",
                str(sample_rate),
                "-ac",
                "1",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(out_path),
            ]
        )
    elif suffix == ".mp3":
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(story_wav),
                "-ar",
                str(sample_rate),
                "-ac",
                "1",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(out_path),
            ]
        )
    else:
        import shutil

        shutil.copy2(story_wav, out_path)
