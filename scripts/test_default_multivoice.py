#!/usr/bin/env python3
"""Default (SYSTEM_USER_ID) multi-voice plans and generation routing."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from default_generation import (
    _load_role_voice_maps,
    build_default_generation_plan,
    effective_voice_for_role,
    resolve_narrator_voice,
    role_voice_map_for_story,
)
from default_narration import (
    DEFAULT_VOICE_IDS,
    LOCAL_ONLY_VOICES,
    LocalOnlyVoicePaths,
    SYSTEM_USER_ID,
    can_generate_default_narration,
    local_only_reference_available,
)
from generation_backends import FakeGenerationBackend
from generation_service import GenerationService
from role_assignments import story_speaker_keys
from default_narration import story_default_voice
from story_catalog import list_stories
from story_multivoice import story_markup_body_from_id
from voice_slots import NARRATOR_ROLE_KEY

# Former Seraphina roles — must map to a non-catalog-narrator voice when possible.
SERAPHINA_REMOVED_ROLES: dict[str, str] = {
    "geum-dokki-eun-dokki": "이웃",
    "hokburi-yeonggam": "욕심쟁이",
    "ureong-gaksi": "원님",
    "cheong-gaeguri": "이웃",
    "tokki-ui-gan": "토끼",
    "gyeonu-wa-jiknyeo": "옥황상제",
    "namukkun-gwa-seonnyeo": "사슴",
    "gae-wa-goyangi-ui-guseul": "할아버지",
}


@contextmanager
def _isolated_local_only_refs(tmp_path: Path, *, available: frozenset[str]):
    """Point harry/anna local-only paths at temp dirs (ignore repo data/voice/*)."""
    prior = {k: LOCAL_ONLY_VOICES[k] for k in LOCAL_ONLY_VOICES}
    isolated_root = tmp_path / "isolated_local_only"
    try:
        for voice, paths in prior.items():
            if voice in available:
                local_wav = isolated_root / voice / "reference.wav"
                local_wav.parent.mkdir(parents=True, exist_ok=True)
                local_wav.write_bytes(b"RIFF" + voice.encode()[:4])
            else:
                local_wav = isolated_root / voice / "definitely_missing.wav"
            LOCAL_ONLY_VOICES[voice] = LocalOnlyVoicePaths(
                subdir=paths.subdir,
                local_wav=local_wav,
            )
        yield
    finally:
        for voice, paths in prior.items():
            LOCAL_ONLY_VOICES[voice] = paths


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


def test_seraphina_removed_roles_not_catalog_narrator_voice() -> None:
    _load_role_voice_maps.cache_clear()
    for story_id, role in SERAPHINA_REMOVED_ROLES.items():
        role_map = role_voice_map_for_story(story_id)
        catalog_narrator = story_default_voice(story_id)
        assert role in role_map, (story_id, role)
        assert role_map[role] != catalog_narrator, (story_id, role, role_map[role])


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
            assert plan.assignments["이웃"] == plan.assignments["나무꾼"]
            assert plan.markup_body == story_markup_body_from_id("geum-dokki-eun-dokki")
    finally:
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice


def test_missing_mapped_voice_falls_back_but_still_generates() -> None:
    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"
    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    old_audio = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR")
    role_map = role_voice_map_for_story("geum-dokki-eun-dokki")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(
                _voice_fixtures(tmp_path, script, voices=("harry", "dana"))
            )
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(tmp_path / "audio")

            with _isolated_local_only_refs(tmp_path, available=frozenset({"harry"})):
                assert not local_only_reference_available("anna")
                _load_role_voice_maps.cache_clear()
                resolved = resolve_narrator_voice("geum-dokki-eun-dokki")
                assert resolved == "harry"
                assert (
                    effective_voice_for_role(
                        "산신령",
                        story_id="geum-dokki-eun-dokki",
                        narrator_voice=resolved,
                        role_map=role_map,
                    )
                    == "harry"
                )
                plan = build_default_generation_plan("geum-dokki-eun-dokki")
                assert len(plan.slot_refs) == 2
                assert plan.assignments["산신령"] == plan.assignments[NARRATOR_ROLE_KEY]

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

            voice_root = Path(os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"])
            anna_dir = voice_root / "anna"
            anna_dir.mkdir(parents=True, exist_ok=True)
            (anna_dir / "reference.wav").write_bytes(b"RIFFanna")
            (anna_dir / "reference.txt").write_text(script + "\n", encoding="utf-8")
            with _isolated_local_only_refs(tmp_path, available=frozenset({"harry", "anna"})):
                assert local_only_reference_available("anna")
                assert (
                    effective_voice_for_role(
                        "산신령",
                        story_id="geum-dokki-eun-dokki",
                        narrator_voice="harry",
                        role_map=role_map,
                    )
                    == "anna"
                )
    finally:
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice
        if old_audio is None:
            os.environ.pop("STORY_VOICE_DEFAULT_AUDIO_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = old_audio


def test_missing_narrator_voice_falls_back_dana_harry_anna() -> None:
    from default_narration import LOCAL_ONLY_VOICES, LocalOnlyVoicePaths

    record = ROOT / "content" / "record_script.txt"
    script = record.read_text(encoding="utf-8").strip() if record.is_file() else "테스트"
    old_voice = os.environ.get("STORY_VOICE_DEFAULT_VOICE_DIR")
    old_audio = os.environ.get("STORY_VOICE_DEFAULT_AUDIO_DIR")
    prior_harry = LOCAL_ONLY_VOICES["harry"]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice_root = _voice_fixtures(tmp_path, script, voices=("dana",))
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(voice_root)
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(tmp_path / "audio")
            LOCAL_ONLY_VOICES["harry"] = LocalOnlyVoicePaths(
                subdir="harry",
                local_wav=tmp_path / "missing" / "reference.wav",
            )
            assert can_generate_default_narration("geum-dokki-eun-dokki")
            assert resolve_narrator_voice("geum-dokki-eun-dokki") == "dana"

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
    finally:
        LOCAL_ONLY_VOICES["harry"] = prior_harry
        if old_voice is None:
            os.environ.pop("STORY_VOICE_DEFAULT_VOICE_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_VOICE_DIR"] = old_voice
        if old_audio is None:
            os.environ.pop("STORY_VOICE_DEFAULT_AUDIO_DIR", None)
        else:
            os.environ["STORY_VOICE_DEFAULT_AUDIO_DIR"] = old_audio


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
    test_seraphina_removed_roles_not_catalog_narrator_voice()
    test_build_default_plan_slots_and_multivoice()
    test_missing_mapped_voice_falls_back_but_still_generates()
    test_missing_narrator_voice_falls_back_dana_harry_anna()
    test_system_user_enqueue_uses_multivoice_backend()
    print("OK: default multivoice tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())