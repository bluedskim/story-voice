#!/usr/bin/env python3
"""TTS model reload after ASR verify unloads the shared StoryGenerator model (no MLX)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generation_backends import MLXGenerationBackend
from story_narration import NarrationConfig, TtsSession


class _FakeStoryGenerator:
    """Minimal StoryGenerator stand-in for backend multivoice calls."""

    def __init__(self) -> None:
        self._model: object | None = object()
        self.loads = 0
        self.unloads = 0
        self.max_chars = 120
        self.sentence_pause = 0.35
        self.paragraph_pause = 0.75
        self.temperature = None
        self.dialogue_style = True
        self.narration_config = NarrationConfig(verify_asr=False)
        self._TtsSession = TtsSession

    def _load_model(self) -> object:
        if self._model is None:
            self.loads += 1
            self._model = object()
        return self._model

    def _unload_model(self) -> None:
        self.unloads += 1
        self._model = None


def test_tts_session_release_unloads_generator_then_load_model_recovers() -> None:
    gen = _FakeStoryGenerator()
    session = TtsSession(gen._load_model, gen._unload_model)
    assert gen._load_model() is not None
    session.release()
    assert gen._model is None
    reloaded = gen._load_model()
    assert reloaded is not None
    assert gen.loads == 1


def test_multivoice_backend_reload_after_asr_job() -> None:
    """Regression: ASR job ends with TTS unloaded; next non-ASR job must pass a loaded model."""
    import role_assignments
    import story_multivoice

    gen = _FakeStoryGenerator()
    models_seen: list[object | None] = []

    def fake_narrate(
        _markup,
        out_path,
        _resolve,
        model,
        *,
        on_chunk=None,
        narration_config=None,
        tts_session=None,
        **kwargs,
    ) -> None:
        del kwargs
        models_seen.append(model)
        if narration_config and narration_config.verify_asr:
            assert tts_session is not None
            _ = tts_session.model
            tts_session.release()
        out_path.write_bytes(b"RIFF")
        if on_chunk:
            on_chunk(1, 1)

    original = story_multivoice.narrate_story_multivoice
    old_resolve = role_assignments.resolved_slot_for_role
    old_load = story_multivoice.load_voice_reference
    story_multivoice.narrate_story_multivoice = fake_narrate
    role_assignments.resolved_slot_for_role = lambda *_a, **_k: 1
    story_multivoice.load_voice_reference = lambda *_a, **_k: MagicMock(audio_array=lambda: None)
    try:
        backend = MLXGenerationBackend()
        backend._generator = gen  # type: ignore[assignment]

        plan = MagicMock()
        plan.multivoice = True
        plan.story_id = "horangi-wa-gotgam"
        plan.markup_body = "한 줄."
        plan.assignments = {}
        plan.slot_refs = {1: (Path("/dev/null"), Path("/dev/null"))}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.m4a"

            def on_progress(_c: int, _t: int, _sid: str) -> None:
                pass

            backend.generate_member_story(plan, "ignored", out, on_progress, verify_asr=True)
            assert gen._model is None

            gen.narration_config.verify_asr = False
            backend.generate_member_story(plan, "ignored", out, on_progress, verify_asr=False)

        assert len(models_seen) == 2
        assert models_seen[0] is not None
        assert models_seen[1] is not None, "second job must receive reloaded model, not None"
        assert gen.loads >= 1
    finally:
        story_multivoice.narrate_story_multivoice = original
        role_assignments.resolved_slot_for_role = old_resolve
        story_multivoice.load_voice_reference = old_load


def main() -> int:
    test_tts_session_release_unloads_generator_then_load_model_recovers()
    test_multivoice_backend_reload_after_asr_job()
    print("OK: TTS model reload after ASR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())