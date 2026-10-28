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
    apply_chunk_lead_fade_in,
    apply_chunk_tail_pad,
    apply_dialogue_style,
    apply_final_loudnorm_if_enabled,
    build_dialogue_middle_chain,
    build_dialogue_tail_filter,
    compute_chunk_tail_pad_sec,
    encode_story_from_wav,
    loudnorm_two_pass_wav,
    probe_duration_sec,
    trailing_silence_sec,
    load_mono_float_samples,
    volumedetect_mean_db,
)
from clone_story import ffmpeg_concat_wav, write_chunk_concat_list
from audio_quality_config import (
    DEFAULT_CHUNK_TAIL_PAD_SEC,
    DEFAULT_CHUNK_TAIL_GUARD_EXTRA_SEC,
    chunk_tail_pad_sec,
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


def test_chunk_lead_cleanup_removes_pre_speech_click() -> None:
    """Regression: hard concat exposed TTS leading clicks in inter-chunk silence."""
    import numpy as np
    import wave

    sr = 24000
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "clicky.wav"
        n_lead = int(0.02 * sr)
        n_click = int(0.025 * sr)
        n_gap = int(0.04 * sr)
        n_speech = int(0.25 * sr)
        total = n_lead + n_click + n_gap + n_speech
        sig = np.zeros(total, dtype=np.float32)
        off = n_lead
        sig[off : off + n_click] = 0.45 * np.hanning(n_click)
        off += n_click + n_gap
        t = np.arange(n_speech) / sr
        sig[off:] = 0.2 * np.sin(2 * np.pi * 440 * t)
        with wave.open(str(src), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((sig * 32767).astype(np.int16).tobytes())
        click_region = slice(n_lead, n_lead + n_click + n_gap)
        before = float(np.max(np.abs(sig[click_region])))
        apply_chunk_lead_fade_in(src, sr, fade_sec=0.025)
        samples = load_mono_float_samples(src)
        after = float(np.max(np.abs(samples[click_region])))
        speech_peak = float(np.max(np.abs(samples[n_lead + n_click + n_gap :])))
        assert before > 0.2
        assert after < before * 0.08
        assert speech_peak > 0.05


def test_chunk_lead_preserves_soft_onset() -> None:
    """Regression: lead-strip must not zero quiet attack / first syllable before sustained hold."""
    import numpy as np
    import wave

    sr = 24000
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "soft.wav"
        n = int(0.35 * sr)
        t = np.arange(n, dtype=np.float64) / sr
        env = np.linspace(0.03, 0.28, n, dtype=np.float32)
        sig = (env * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        early = slice(0, int(0.06 * sr))
        before_peak = float(np.max(np.abs(sig[early])))
        with wave.open(str(src), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((sig * 32767).astype(np.int16).tobytes())
        apply_chunk_lead_fade_in(src, sr, fade_sec=0.025)
        out = load_mono_float_samples(src)
        after_peak = float(np.max(np.abs(out[early])))
        assert before_peak > 0.01
        assert after_peak >= before_peak * 0.45


def test_chunk_lead_fade_aligns_with_speech_onset() -> None:
    """Regression: fade at t=0 only affects TTS padding; speech attack stays abrupt."""
    import numpy as np
    import wave

    from audio_post import speech_onset_sample

    sr = 24000
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "padded_tts.wav"
        n_lead = int(0.12 * sr)
        n_speech = int(0.25 * sr)
        sig = np.zeros(n_lead + n_speech, dtype=np.float32)
        sig[:n_lead] = np.random.default_rng(0).normal(0, 0.002, n_lead).astype(np.float32)
        t = np.arange(n_speech, dtype=np.float64) / sr
        sig[n_lead:] = (0.28 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        with wave.open(str(src), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((sig * 32767).astype(np.int16).tobytes())
        onset = speech_onset_sample(sig, sr)
        assert onset >= n_lead - sr // 50  # ~120 ms lead
        raw_attack = float(np.max(np.abs(sig[onset : onset + int(0.008 * sr)])))
        apply_chunk_lead_fade_in(src, sr, fade_sec=0.025)
        out = load_mono_float_samples(src)
        soft_attack = float(np.max(np.abs(out[onset : onset + int(0.008 * sr)])))
        assert raw_attack > 0.15
        assert soft_attack < raw_attack * 0.35


def test_chunk_tail_pad_extends_duration() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.wav"
        make_tone_wav(src, 0.2)
        before = probe_duration_sec(src)
        expected = compute_chunk_tail_pad_sec(src, 24000)
        apply_chunk_tail_pad(src, 24000)
        after = probe_duration_sec(src)
        assert after - before >= expected - 0.002


def test_tail_guard_extra_on_tight_tts_end() -> None:
    """Sine ending at full level → no natural tail silence → baseline + guard extra."""
    _clear_dialogue_env()
    os.environ.pop("STORY_VOICE_CHUNK_TAIL_GUARD", None)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "tight.wav"
        make_tone_wav(src, 0.15)
        samples = load_mono_float_samples(src)
        assert trailing_silence_sec(samples, 24000) < 0.01
        pad = compute_chunk_tail_pad_sec(src, 24000)
        assert pad >= chunk_tail_pad_sec() + DEFAULT_CHUNK_TAIL_GUARD_EXTRA_SEC - 0.001
        assert 0.080 <= pad <= 0.100


def test_tail_guard_skips_extra_when_trailing_silence_present() -> None:
    import numpy as np
    import wave

    _clear_dialogue_env()
    sr = 24000
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "loose.wav"
        n_speech = int(0.2 * sr)
        n_sil = int(0.08 * sr)
        sig = np.zeros(n_speech + n_sil, dtype=np.float32)
        t = np.arange(n_speech) / sr
        sig[:n_speech] = 0.2 * np.sin(2 * np.pi * 440 * t)
        with wave.open(str(src), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((sig * 32767).astype(np.int16).tobytes())
        samples = load_mono_float_samples(src)
        assert trailing_silence_sec(samples, sr) >= 0.07
        pad = compute_chunk_tail_pad_sec(src, sr)
        assert pad <= chunk_tail_pad_sec() + 0.001


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


def _speech_tail_peak(path: Path, speech_end_sec: float, window_ms: float = 25.0, sr: int = 24000) -> float:
    import numpy as np

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
    end = min(len(samples), int(speech_end_sec * sr))
    start = max(0, end - int(window_ms / 1000.0 * sr))
    if end <= start:
        return 0.0
    return float(np.max(np.abs(samples[start:end])))


def test_narration_pipeline_preserves_speech_tail() -> None:
    """Narration path: chunk pad → concat pause → loudnorm → AAC keeps decay tail."""
    import wave

    sr = 24000
    import numpy as np

    speech_sec = 0.55
    n1 = int(0.45 * sr)
    n2 = int(0.10 * sr)
    t1 = np.arange(n1) / sr
    sig1 = 0.25 * np.sin(2 * np.pi * 440 * t1)
    t2 = np.arange(n2) / sr
    sig2 = 0.25 * np.exp(-t2 / 0.05) * np.sin(2 * np.pi * 440 * (0.45 + t2))
    sig = np.concatenate([sig1, sig2]).astype(np.float32)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chunk = tmp_path / "chunk.wav"
        with wave.open(str(chunk), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((sig * 32767).astype(np.int16).tobytes())

        ref_peak = _speech_tail_peak(chunk, speech_sec)
        apply_chunk_tail_pad(chunk, sr)

        sil = tmp_path / "sil.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={sr}:cl=mono",
                "-t",
                "0.35",
                "-c:a",
                "pcm_s16le",
                str(sil),
            ],
            check=True,
        )
        lst = tmp_path / "list.txt"
        chunks_meta = [("narration text", "sentence", "narration")]
        write_chunk_concat_list(lst, [chunk], chunks_meta, sil, sil)
        story = tmp_path / "story.wav"
        ffmpeg_concat_wav(str(lst), sr, story)
        loudnorm_two_pass_wav(story, tmp_path / "ln.wav", -16.0)
        subprocess.run(
            ["cp", str(tmp_path / "ln.wav"), str(story)],
            check=True,
        )
        m4a = tmp_path / "out.m4a"
        encode_story_from_wav(story, m4a, sr)
        dec = tmp_path / "dec.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(m4a), str(dec)],
            check=True,
        )
        out_peak = _speech_tail_peak(dec, speech_sec)
        assert ref_peak > 0.01
        assert out_peak >= ref_peak * 0.8


def test_concat_list_uses_retry_chunk_paths() -> None:
    """After ASR retry, concat must reference the winning wav path (not the first attempt)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        retry = tmp_path / "chunk_0000_retry1.wav"
        sil = tmp_path / "silence_sentence.wav"
        retry.write_bytes(b"")
        sil.write_bytes(b"")
        lst = tmp_path / "list.txt"
        meta = [("one", "sentence", "narration")]
        write_chunk_concat_list(lst, [retry], meta, sil, sil)
        text = lst.read_text(encoding="utf-8")
        assert "chunk_0000_retry1.wav" in text
        assert "chunk_0000.wav'" not in text


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
    test_chunk_lead_cleanup_removes_pre_speech_click()
    test_chunk_lead_preserves_soft_onset()
    test_chunk_lead_fade_aligns_with_speech_onset()
    test_chunk_tail_pad_extends_duration()
    test_tail_guard_extra_on_tight_tts_end()
    test_tail_guard_skips_extra_when_trailing_silence_present()
    test_narration_pipeline_preserves_speech_tail()
    test_concat_list_uses_retry_chunk_paths()
    test_dialogue_style_preserves_speech_tail_energy()
    test_parse_loudnorm_json_ffmpeg9_trailing_lines()
    test_parse_loudnorm_json_brace_noise_before()
    test_loudnorm_fallback_keeps_input_on_failure()
    test_apply_eq_loudness_match()
    print("OK: audio post tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
