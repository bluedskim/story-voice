#!/usr/bin/env python3
"""Role assignment validation, multivoice plan, atomic overwrite."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _write_slot(uid: int, slot_id: int, text: str = "script") -> None:
    from voice_slots import slot_dir, slot_ref_txt, slot_ref_wav, ensure_slot_meta_row

    ensure_slot_meta_row(uid, slot_id, f"slot{slot_id}")
    slot_dir(uid, slot_id).mkdir(parents=True, exist_ok=True)
    slot_ref_wav(uid, slot_id).write_bytes(b"RIFF")
    slot_ref_txt(uid, slot_id).write_text(text + "\n", encoding="utf-8")


def test_role_assignment_validation_and_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        from role_assignments import (
            NARRATOR_ROLE_KEY,
            load_assignment,
            resolved_slot_for_role,
            save_assignment,
        )

        uid = 10
        _write_slot(uid, 1)
        _write_slot(uid, 2)
        saved = save_assignment(
            uid,
            "geum-dokki-eun-dokki",
            {NARRATOR_ROLE_KEY: 1, "나무꾼": 2},
        )
        assert saved["valid"] is True
        assert resolved_slot_for_role(uid, "geum-dokki-eun-dokki", "산신령", saved["assignments"]) == 1
        assert resolved_slot_for_role(uid, "geum-dokki-eun-dokki", "나무꾼", saved["assignments"]) == 2


def test_stale_assignment_invalidated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        from role_assignments import invalidate_if_stale, load_assignment, save_assignment, NARRATOR_ROLE_KEY
        import time

        uid = 11
        _write_slot(uid, 1)
        save_assignment(uid, "eunhye-gapeun-kkachi", {NARRATOR_ROLE_KEY: 1})
        wav = Path(tmp) / str(uid) / "voice" / "slots" / "1" / "reference.wav"
        time.sleep(0.05)
        wav.write_bytes(b"RIFF2")
        assert invalidate_if_stale(uid, "eunhye-gapeun-kkachi") is True
        loaded = load_assignment(uid, "eunhye-gapeun-kkachi")
        assert loaded["assignments"] == {}


def test_member_plan_multivoice_vs_single() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        from member_generation import build_member_generation_plan
        from role_assignments import save_assignment, NARRATOR_ROLE_KEY

        uid = 12
        _write_slot(uid, 1)
        plan_single = build_member_generation_plan(uid, "geum-dokki-eun-dokki")
        assert plan_single.multivoice is False

        _write_slot(uid, 2)
        save_assignment(uid, "geum-dokki-eun-dokki", {NARRATOR_ROLE_KEY: 1, "나무꾼": 2})
        plan_multi = build_member_generation_plan(uid, "geum-dokki-eun-dokki")
        assert plan_multi.multivoice is True
        assert len(plan_multi.slot_refs) >= 2


def test_fake_backend_chunk_slot_consistency() -> None:
    from generation_backends import FakeGenerationBackend
    from member_generation import build_member_generation_plan
    from role_assignments import save_assignment, NARRATOR_ROLE_KEY

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 13
        _write_slot(uid, 1)
        _write_slot(uid, 2)
        save_assignment(uid, "geum-dokki-eun-dokki", {NARRATOR_ROLE_KEY: 1, "나무꾼": 2, "산신령": 1})
        plan = build_member_generation_plan(uid, "geum-dokki-eun-dokki")
        backend = FakeGenerationBackend(chunk_delay=0)
        out = Path(tmp) / "out.m4a"
        backend.generate_member_story(plan, "ignored", out, lambda *a: None)
        assert backend.last_multivoice is True
        assert backend.last_chunk_slot_ids
        assert all(sid in plan.slot_refs for sid in backend.last_chunk_slot_ids)


def test_atomic_overwrite_pattern() -> None:
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        final = Path(tmp) / "story.m4a"
        final.write_bytes(b"old")
        staging = Path(tmp) / "story.job.m4a"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                "0.1",
                "-c:a",
                "aac",
                str(staging),
            ],
            check=True,
        )
        os.replace(staging, final)
        assert final.is_file()
        assert not staging.exists()
        assert final.stat().st_size > 0


def main() -> int:
    test_role_assignment_validation_and_fallback()
    test_stale_assignment_invalidated()
    test_member_plan_multivoice_vs_single()
    test_fake_backend_chunk_slot_consistency()
    test_atomic_overwrite_pattern()
    print("OK: multivoice product tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
