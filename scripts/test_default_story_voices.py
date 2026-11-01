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

from default_narration import ensure_default_reference_for_story, story_default_voice, voice_reference_dir
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


def test_generation_uses_story_voice_reference() -> None:
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"

    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    old_audio = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice_root = tmp_path / "voices"
            audio_dir = tmp_path / "audio_default"
            for voice in ("harry", "dana"):
                vdir = voice_root / voice
                vdir.mkdir(parents=True)
                ref_wav = vdir / "reference.wav"
                ref_wav.write_bytes(b"RIFF" + b"\x00" * 40)
                (vdir / "reference.txt").write_text(script + "\n", encoding="utf-8")

            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(voice_root)
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(audio_dir)

            harry_ref, _ = ensure_default_reference_for_story("geum-dokki-eun-dokki")
            dana_ref, _ = ensure_default_reference_for_story("ui-joeun-hyeongje")
            assert harry_ref.parent == voice_reference_dir("harry")
            assert dana_ref.parent == voice_reference_dir("dana")

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


def main() -> int:
    test_catalog_default_voices()
    test_generation_uses_story_voice_reference()
    print("OK: default story voices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
