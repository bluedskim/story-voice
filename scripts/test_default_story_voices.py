#!/usr/bin/env python3
"""Per-story default narrator voice (Harry / Dana / Anna) for shared catalog audio."""

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
    LOCAL_ONLY_VOICES,
    LocalOnlyVoicePaths,
    can_generate_default_narration,
    ensure_default_reference,
    ensure_default_reference_for_story,
    local_only_reference_available,
    resolve_local_only_reference_wav,
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
        "hokburi-yeonggam": "anna",
        "horangi-wa-gotgam": "harry",
        "eunhye-gapeun-kkachi": "dana",
        "tokki-ui-gan": "harry",
        "ureong-gaksi": "dana",
        "cheong-gaeguri": "anna",
        "gyeonu-wa-jiknyeo": "harry",
        "namukkun-gwa-seonnyeo": "dana",
        "gae-wa-goyangi-ui-guseul": "anna",
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
            anna_dir = dana_root / "anna"
            anna_dir.mkdir()
            (anna_dir / "reference.wav").write_bytes(b"RIFF" + b"\x02" * 40)
            (anna_dir / "reference.txt").write_text(script + "\n", encoding="utf-8")

            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(dana_root)
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(audio_dir)

            harry_ref, _ = ensure_default_reference_for_story("geum-dokki-eun-dokki")
            dana_ref, _ = ensure_default_reference_for_story("ui-joeun-hyeongje")
            anna_ref, _ = ensure_default_reference_for_story("hokburi-yeonggam")
            assert dana_ref.parent == dana_root
            assert harry_ref == harry_dir / "reference.wav"
            assert anna_ref == anna_dir / "reference.wav"

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


def test_local_only_missing_skips_without_dana_fallback(voice: str, story_id: str) -> None:
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"

    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    old_audio = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR")
    prior_paths = LOCAL_ONLY_VOICES[voice]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dana_root = tmp_path / "dana_default"
            audio_dir = tmp_path / "audio_default"
            dana_root.mkdir(parents=True)
            (dana_root / "reference.wav").write_bytes(b"RIFF" + b"\x00" * 40)
            (dana_root / "reference.txt").write_text(script + "\n", encoding="utf-8")

            # Do not rely on gitignored production refs under data/voice/{harry,anna}/.
            LOCAL_ONLY_VOICES[voice] = LocalOnlyVoicePaths(
                subdir=prior_paths.subdir,
                local_wav=tmp_path / "isolated_local" / voice / "reference.wav",
            )

            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(dana_root)
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(audio_dir)

            assert not local_only_reference_available(voice)
            assert not can_generate_default_narration(story_id)
            assert can_generate_default_narration("ui-joeun-hyeongje")

            try:
                ensure_default_reference(voice)
            except DefaultReferenceUnavailable as exc:
                assert exc.voice == voice
            else:
                raise AssertionError(f"expected DefaultReferenceUnavailable for missing {voice} wav")

            backend = FakeGenerationBackend(chunk_delay=0)
            svc = GenerationService(backend=backend)
            result = svc.enqueue_story(story_id, SYSTEM_USER_ID)
            assert result.created
            deadline = time.time() + 5.0
            job = svc._get_job(result.job.job_id)
            while job and job.state.value not in {"done", "failed"} and time.time() < deadline:
                time.sleep(0.05)
                job = svc._get_job(result.job.job_id)
            assert job and job.state.value == "done"
            assert backend.last_ref_wav is None
            assert not (audio_dir / f"{story_id}.m4a").is_file()

            assert resolve_local_only_reference_wav(voice) is None
    finally:
        LOCAL_ONLY_VOICES[voice] = prior_paths
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice
        if old_audio is None:
            os.environ.pop("STORY_VOICE_DEFAULT_AUDIO_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = old_audio


def test_harry_missing_skips_without_dana_fallback() -> None:
    test_local_only_missing_skips_without_dana_fallback("harry", "geum-dokki-eun-dokki")


def test_anna_missing_skips_without_dana_fallback() -> None:
    test_local_only_missing_skips_without_dana_fallback("anna", "hokburi-yeonggam")


def test_anna_prefers_packaged_then_local_wav() -> None:
    from user_storage import REF_WAV_NAME

    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"

    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    prior = LOCAL_ONLY_VOICES["anna"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dana_root = tmp_path / "dana_default"
            dana_root.mkdir()
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(dana_root)

            local_wav = tmp_path / "anna_local.wav"
            local_wav.write_bytes(b"RIFF" + b"\x03" * 40)
            LOCAL_ONLY_VOICES["anna"] = LocalOnlyVoicePaths(
                subdir="anna",
                local_wav=local_wav,
            )

            assert resolve_local_only_reference_wav("anna") == local_wav
            wav, _ = ensure_default_reference("anna")
            assert wav == local_wav

            packaged_dir = dana_root / "anna"
            packaged_dir.mkdir()
            packaged_wav = packaged_dir / REF_WAV_NAME
            packaged_wav.write_bytes(b"RIFF" + b"\x04" * 40)
            (packaged_dir / "reference.txt").write_text(script + "\n", encoding="utf-8")

            assert resolve_local_only_reference_wav("anna") == packaged_wav
            wav2, _ = ensure_default_reference("anna")
            assert wav2 == packaged_wav
    finally:
        LOCAL_ONLY_VOICES["anna"] = prior
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice


def main() -> int:
    test_catalog_default_voices()
    test_dana_uses_legacy_default_root()
    test_generation_uses_story_voice_reference()
    test_harry_missing_skips_without_dana_fallback()
    test_anna_missing_skips_without_dana_fallback()
    test_anna_prefers_packaged_then_local_wav()
    print("OK: default story voices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
