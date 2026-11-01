#!/usr/bin/env python3
"""Per-story default narrator voice (Harry / Dana) for shared catalog audio."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from default_narration import (
    DefaultReferenceUnavailable,
    can_generate_default_narration,
    ensure_default_reference,
    ensure_default_reference_for_story,
    harry_reference_available,
    resolve_harry_reference_wav,
    story_default_voice,
    voice_reference_dir,
)
from generation_backends import FakeGenerationBackend
from generation_service import SYSTEM_USER_ID, GenerationService
from story_catalog import list_stories


def test_catalog_default_voices() -> None:
    expected = {
        "ui-joeun-hyeongje": "dana",
        "geum-dokki-eun-dokki": "harry",
        "hokburi-yeonggam": "dana",
        "haenim-dalnim": "harry",
        "heungbu-nolbu": "dana",
    }
    for story in list_stories():
        assert story.default_voice == expected[story.id], story.id
        assert story_default_voice(story.id) == expected[story.id]


def test_dana_uses_legacy_default_root() -> None:
    assert voice_reference_dir("dana") == voice_reference_dir("dana").resolve()
    root = voice_reference_dir("dana")
    assert root.name == "default" or os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")


def test_generation_uses_story_voice_reference() -> None:
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"

    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    old_audio = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dana_root = tmp_path / "dana_default"
            audio_dir = tmp_path / "audio_default"
            dana_root.mkdir(parents=True)
            (dana_root / "reference.wav").write_bytes(b"RIFF" + b"\x00" * 40)
            (dana_root / "reference.txt").write_text(script + "\n", encoding="utf-8")
            harry_dir = dana_root / "harry"
            harry_dir.mkdir()
            (harry_dir / "reference.wav").write_bytes(b"RIFF" + b"\x01" * 40)
            (harry_dir / "reference.txt").write_text(script + "\n", encoding="utf-8")

            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(dana_root)
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(audio_dir)

            harry_ref, _ = ensure_default_reference_for_story("geum-dokki-eun-dokki")
            dana_ref, _ = ensure_default_reference_for_story("ui-joeun-hyeongje")
            assert dana_ref.parent == dana_root
            assert harry_ref == harry_dir / "reference.wav"

            backend = FakeGenerationBackend(chunk_delay=0)
            svc = GenerationService(backend=backend)
            result = svc.enqueue_story("geum-dokki-eun-dokki", SYSTEM_USER_ID)
            assert result.created

            deadline = time.time() + 5.0
            job = svc._get_job(result.job.job_id)
            while job and job.state.value not in {"done", "failed"} and time.time() < deadline:
                time.sleep(0.05)
                job = svc._get_job(result.job.job_id)
            assert job and job.state.value == "done", job.error if job else "no job"
            assert backend.last_ref_wav == harry_ref
    finally:
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice
        if old_audio is None:
            os.environ.pop("STORY_VOICE_DEFAULT_AUDIO_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = old_audio


def test_harry_missing_skips_without_dana_fallback() -> None:
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"

    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    old_audio = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dana_root = tmp_path / "dana_default"
            audio_dir = tmp_path / "audio_default"
            dana_root.mkdir(parents=True)
            (dana_root / "reference.wav").write_bytes(b"RIFF" + b"\x00" * 40)
            (dana_root / "reference.txt").write_text(script + "\n", encoding="utf-8")

            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(dana_root)
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(audio_dir)

            assert not harry_reference_available()
            assert not can_generate_default_narration("geum-dokki-eun-dokki")
            assert can_generate_default_narration("ui-joeun-hyeongje")

            try:
                ensure_default_reference("harry")
            except DefaultReferenceUnavailable:
                pass
            else:
                raise AssertionError("expected DefaultReferenceUnavailable for missing Harry wav")

            backend = FakeGenerationBackend(chunk_delay=0)
            svc = GenerationService(backend=backend)
            result = svc.enqueue_story("geum-dokki-eun-dokki", SYSTEM_USER_ID)
            assert result.created
            deadline = time.time() + 5.0
            job = svc._get_job(result.job.job_id)
            while job and job.state.value not in {"done", "failed"} and time.time() < deadline:
                time.sleep(0.05)
                job = svc._get_job(result.job.job_id)
            assert job and job.state.value == "done"
            assert backend.last_ref_wav is None
            assert not (audio_dir / "geum-dokki-eun-dokki.m4a").is_file()

            harry_wav = resolve_harry_reference_wav()
            assert harry_wav is None
    finally:
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice
        if old_audio is None:
            os.environ.pop("STORY_VOICE_DEFAULT_AUDIO_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = old_audio


def main() -> int:
    test_catalog_default_voices()
    test_dana_uses_legacy_default_root()
    test_generation_uses_story_voice_reference()
    test_harry_missing_skips_without_dana_fallback()
    print("OK: default story voices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
