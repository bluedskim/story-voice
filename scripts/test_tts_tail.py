#!/usr/bin/env python3
"""TTS trailing-ellipsis + abrupt-ending detector tests (MLX optional)."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import story_narration
from audio_quality_config import tail_abrupt_retries, tts_trailing_ellipsis_enabled
from story_narration import NarrationConfig, run_asr_verification
from tts_tail import ELLIPSIS, analyze_tail, tts_input_text

SR = 24000


class _env:
    def __init__(self, **values: str | None) -> None:
        self.values = values
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _speech(sec: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(SR * sec)) / SR
    return (amp * np.sin(2 * np.pi * 180 * t) * (1 + 0.3 * np.sin(2 * np.pi * 5 * t))).astype(np.float32)


def abrupt_signal(trailing_silence: float = 0.3) -> np.ndarray:
    x = _speech(0.8)
    x[-int(0.2 * SR):] *= 0.5  # last syllable still loud (~-6 dB)
    return np.concatenate([x, np.zeros(int(SR * trailing_silence), np.float32)])


def decaying_signal(decay_sec: float = 0.12) -> np.ndarray:
    x = _speech(0.8 + decay_sec)
    n = int(SR * decay_sec)
    env = np.ones(len(x), np.float32)
    env[-n:] = np.power(10.0, (-70.0 * np.arange(n) / n) / 20.0)  # 0 -> -70 dB
    return np.concatenate([x * env, np.zeros(int(SR * 0.3), np.float32)])


def test_text_transform() -> None:
    assert tts_input_text("마주쳤어요.", enabled=True) == f"마주쳤어요. {ELLIPSIS}"
    assert tts_input_text('"쌀이 더 필요할 거야."  ', enabled=True) == f'"쌀이 더 필요할 거야." {ELLIPSIS}'
    assert tts_input_text("그런데…", enabled=True) == "그런데…"
    assert tts_input_text("그런데...", enabled=True) == "그런데..."
    assert tts_input_text("", enabled=True) == ""
    assert tts_input_text("마주쳤어요.", enabled=False) == "마주쳤어요."
    with _env(STORY_VOICE_TTS_TRAILING_ELLIPSIS=None):
        assert tts_trailing_ellipsis_enabled() is True
        assert tts_input_text("여물었답니다.").endswith(f" {ELLIPSIS}")
    with _env(STORY_VOICE_TTS_TRAILING_ELLIPSIS="0"):
        assert tts_input_text("여물었답니다.") == "여물었답니다."
    with _env(STORY_VOICE_TAIL_ABRUPT_RETRIES=None):
        assert tail_abrupt_retries() == 2
    with _env(STORY_VOICE_TAIL_ABRUPT_RETRIES="0"):
        assert tail_abrupt_retries() == 0


def test_detector_synthetic() -> None:
    a = analyze_tail(abrupt_signal(), SR)
    assert a.abrupt and a.decay_ms <= 10, a
    eof = analyze_tail(_speech(0.8), SR)  # file ends mid-syllable
    assert eof.abrupt and eof.ends_loud, eof
    for d in (0.06, 0.12, 0.2):
        n = analyze_tail(decaying_signal(d), SR)
        assert not n.abrupt and n.decay_ms >= 20, (d, n)
    assert analyze_tail(decaying_signal(0.12), SR).score > a.score > eof.score
    assert not analyze_tail(np.zeros(10, np.float32), SR).abrupt


def test_asr_scores_original_text() -> None:
    """ASR verify must compare against the original chunk text, not the TTS input."""
    seen_refs: list[str] = []
    seen_tts: list[str] = []

    class FakeAsr:
        def __init__(self, *_a, **_k):
            pass

        def load(self):
            pass

        def unload(self):
            pass

    def fake_score(_asr, _path, reference):
        seen_refs.append(reference)
        return (0.9 if len(seen_refs) == 1 else 0.0), reference

    class FakeSession:
        model = object()

        def release(self):
            pass

    def fake_synth(_m, chunk, path):
        seen_tts.append(tts_input_text(chunk[0], enabled=True))
        return SR

    chunks = [
        ("마주쳤어요.", "sentence", "narration"),
        ('"쌀이 더 필요할 거야."', "sentence", "dialogue"),
        ("여물었답니다.", "paragraph", "narration"),
    ]
    old_asr, old_score = story_narration.MlxQwenAsr, story_narration.score_chunk
    story_narration.MlxQwenAsr, story_narration.score_chunk = FakeAsr, fake_score
    try:
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for i in range(len(chunks)):
                p = Path(td) / f"chunk_{i:04d}.wav"
                p.write_bytes(b"")
                paths.append(p)
            run_asr_verification(chunks, paths, FakeSession(), NarrationConfig(verify_asr=True, max_asr_retries=1), fake_synth)
    finally:
        story_narration.MlxQwenAsr, story_narration.score_chunk = old_asr, old_score
    # 3 initial scores + 1 retry score of chunk 0, all against the original text
    assert seen_refs == [c[0] for c in chunks] + ["마주쳤어요."], seen_refs
    assert seen_tts == [f"마주쳤어요. {ELLIPSIS}"], seen_tts


@dataclass
class _Res:
    audio: np.ndarray
    sample_rate: int = SR


class FakeTtsModel:
    sample_rate = SR

    def __init__(self, takes: list[np.ndarray]) -> None:
        self.takes = takes
        self.texts: list[str] = []

    def generate(self, **kw):
        self.texts.append(kw["text"])
        idx = min(len(self.texts) - 1, len(self.takes) - 1)
        return [_Res(self.takes[idx])]


class FakeRef:
    text = "참조"

    def audio_array(self):
        return np.zeros(10, np.float32)


def test_synthesize_retries_abrupt() -> None:
    try:
        import mlx_audio.audio_io  # noqa: F401
    except Exception:
        print("SKIP: test_synthesize_retries_abrupt (mlx_audio not installed)")
        return
    from clone_story import synthesize_chunk_to_wav

    chunk = ("마주쳤어요.", "sentence", "narration")
    with tempfile.TemporaryDirectory() as td, _env(STORY_VOICE_TAIL_ABRUPT_RETRIES=None, STORY_VOICE_TTS_TRAILING_ELLIPSIS=None):
        out = Path(td) / "c.wav"
        # abrupt, then natural -> 2 generations, ellipsis in TTS text
        m = FakeTtsModel([abrupt_signal(), decaying_signal()])
        synthesize_chunk_to_wav(m, chunk, FakeRef(), "Korean", None, out, False)
        assert len(m.texts) == 2 and all(t == f"마주쳤어요. {ELLIPSIS}" for t in m.texts), m.texts
        assert out.is_file() and out.stat().st_size > 1000
        # always abrupt -> bounded at 1 + retries (default 2)
        m = FakeTtsModel([abrupt_signal()])
        synthesize_chunk_to_wav(m, chunk, FakeRef(), "Korean", None, out, False)
        assert len(m.texts) == 3, m.texts
        # natural first take -> no retry
        m = FakeTtsModel([decaying_signal()])
        synthesize_chunk_to_wav(m, chunk, FakeRef(), "Korean", None, out, False)
        assert len(m.texts) == 1
        with _env(STORY_VOICE_TAIL_ABRUPT_RETRIES="0", STORY_VOICE_TTS_TRAILING_ELLIPSIS="0"):
            m = FakeTtsModel([abrupt_signal()])
            synthesize_chunk_to_wav(m, chunk, FakeRef(), "Korean", None, out, False)
            assert m.texts == ["마주쳤어요."]


def main() -> int:
    test_text_transform()
    test_detector_synthetic()
    test_asr_scores_original_text()
    test_synthesize_retries_abrupt()
    print("OK: tts tail tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
