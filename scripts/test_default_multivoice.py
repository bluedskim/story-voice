#!/usr/bin/env python3
"""Default (SYSTEM_USER_ID) multi-voice plans and generation routing."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from default_generation import (
    _load_role_voice_maps,
    build_default_generation_plan,
    effective_voice_for_role,
    role_voice_map_for_story,
)
from default_narration import DEFAULT_VOICE_IDS, SYSTEM_USER_ID
from generation_backends import FakeGenerationBackend
from generation_service import GenerationService
from role_assignments import story_speaker_keys
from story_catalog import list_stories
from story_multivoice import story_markup_body_from_id
from voice_slots import NARRATOR_ROLE_KEY


def _voice_fixtures(tmp_path: Path, script: str, *, voices: tuple[str, ...]) -> Path:
    voice_root = tmp_path / "voices"
    voice_root.mkdir(parents=True)
    for voice in voices:
        if voice == "dana":
            d = voice_root
        else:
            d = voice_root / voice
            d.mkdir(parents=True, exist_ok=True)
        (d / "reference.wav").write_bytes(b"RIFF" + voice.encode()[:4])
        (d / "reference.txt").write_text(script + "\n", encoding="utf-8")
    return voice_root


def test_default_role_map_matches_stories_and_voices() -> None:
    _load_role_voice_maps.cache_clear()
    maps = _load_role_voice_maps()
    for story in list_stories():
        assert story.id in maps, f"missing default role map for {story.id}"
        role_map = maps[story.id]
        markup = story_markup_body_from_id(story.id)
        speakers = set(story_speaker_keys(markup))
        for role, voice in role_map.items():
            assert role in speakers, (story.id, role, speakers)
            assert voice in DEFAULT_VOICE_IDS, (story.id, role, voice)

        narrator = story.default_voice
        voices_used = {narrator, *role_map.values()}
        assert len(voices_used) >= 2, (story.id, voices_used)
        assert len(voices_used) <= 3, (story.id, voices_used)


def test_build_default_plan_slots_and_multivoice() -> None:
    _load_role_voice_maps.cache_clear()
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"
    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(
                _voice_fixtures(Path(tmp), script, voices=("dana", "harry", "anna"))
            )
            plan = build_default_generation_plan("geum-dokki-eun-dokki")
            assert plan.multivoice is True
            assert len(plan.slot_refs) == 3
            assert plan.assignments[NARRATOR_ROLE_KEY] == 1
            assert plan.assignments["나무꾼"] != plan.assignments["산신령"]
            assert plan.markup_body == story_markup_body_from_id("geum-dokki-eun-dokki")
    finally:
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice


def test_missing_role_voice_falls_back_to_narrator() -> None:
    narrator = "harry"
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"
    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(
                _voice_fixtures(Path(tmp), script, voices=("harry", "dana"))
            )
            assert (
                effective_voice_for_role(
                    "산신령",
                    story_id="geum-dokki-eun-dokki",
                    narrator_voice=narrator,
                    role_map=role_voice_map_for_story("geum-dokki-eun-dokki"),
                )
                == narrator
            )
            _load_role_voice_maps.cache_clear()
            plan = build_default_generation_plan("geum-dokki-eun-dokki")
            assert len(plan.slot_refs) == 2
            assert plan.assignments["산신령"] == plan.assignments[NARRATOR_ROLE_KEY]
    finally:
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice


def test_system_user_enqueue_uses_multivoice_backend() -> None:
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"
    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    old_audio = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice_root = _voice_fixtures(tmp_path, script, voices=("dana", "harry", "anna"))
            audio_dir = tmp_path / "audio"
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(voice_root)
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(audio_dir)

            backend = FakeGenerationBackend(chunk_delay=0)
            svc = GenerationService(backend=backend)
            result = svc.enqueue_story("ui-joeun-hyeongje", SYSTEM_USER_ID)
            assert result.created
            deadline = time.time() + 5.0
            job = svc._get_job(result.job.job_id)
            while job and job.state.value not in {"done", "failed"} and time.time() < deadline:
                time.sleep(0.05)
                job = svc._get_job(result.job.job_id)
            assert job and job.state.value == "done", job.error if job else "no job"
            assert backend.last_multivoice is True
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
    test_default_role_map_matches_stories_and_voices()
    test_build_default_plan_slots_and_multivoice()
    test_missing_role_voice_falls_back_to_narrator()
    test_system_user_enqueue_uses_multivoice_backend()
    print("OK: default multivoice tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())