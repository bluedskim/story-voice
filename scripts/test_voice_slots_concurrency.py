#!/usr/bin/env python3
"""Voice slots.json race-safety and corruption recovery."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from user_storage import REF_TXT_NAME, REF_WAV_NAME, user_voice_dir
from voice_slots import (
    SLOTS_META_NAME,
    create_slot,
    list_voice_slots,
    slot_dir,
    slot_ref_txt,
    slot_ref_wav,
    update_slot_label,
)


def test_list_voice_slots_is_read_only_on_meta() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 100
        create_slot(uid, "라벨 A")
        create_slot(uid, "라벨 B")
        meta_path = user_voice_dir(uid) / SLOTS_META_NAME
        before = meta_path.read_text(encoding="utf-8")
        mtime_before = meta_path.stat().st_mtime
        for _ in range(50):
            slots = list_voice_slots(uid)
            assert len(slots) >= 2
        assert meta_path.read_text(encoding="utf-8") == before
        assert meta_path.stat().st_mtime == mtime_before


def test_concurrent_list_and_label_updates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 101
        create_slot(uid, "시작")
        create_slot(uid, "둘째")
        errors: list[str] = []

        def worker(n: int) -> None:
            try:
                for i in range(30):
                    list_voice_slots(uid)
                    if n % 2 == 0:
                        update_slot_label(uid, 1, f"슬롯1-{n}-{i}")
                    else:
                        update_slot_label(uid, 2, f"슬롯2-{n}-{i}")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()

        assert not errors
        meta_path = user_voice_dir(uid) / SLOTS_META_NAME
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        ids = {int(s["id"]) for s in data["slots"]}
        assert ids == {1, 2}
        labels = {int(s["id"]): s["label"] for s in data["slots"]}
        assert labels[1].startswith("슬롯1-")
        assert labels[2].startswith("슬롯2-")


def test_corrupt_meta_recovers_from_disk() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 102
        slot_dir(uid, 1).mkdir(parents=True, exist_ok=True)
        slot_dir(uid, 2).mkdir(parents=True, exist_ok=True)
        slot_ref_wav(uid, 1).write_bytes(b"RIFF1")
        slot_ref_txt(uid, 1).write_text("one\n", encoding="utf-8")
        slot_ref_wav(uid, 2).write_bytes(b"RIFF2")
        slot_ref_txt(uid, 2).write_text("two\n", encoding="utf-8")
        meta_path = user_voice_dir(uid) / SLOTS_META_NAME
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text("", encoding="utf-8")

        slots = list_voice_slots(uid)
        assert len(slots) == 2
        assert {s["id"] for s in slots} == {1, 2}
        backups = list(meta_path.parent.glob(f"{SLOTS_META_NAME}.corrupt-*"))
        assert backups
        recovered = json.loads(meta_path.read_text(encoding="utf-8"))
        assert len(recovered["slots"]) == 2


def test_orphan_disk_slot_visible_and_not_reused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 103
        create_slot(uid, "첫번째")
        slot_dir(uid, 2).mkdir(parents=True, exist_ok=True)
        slot_ref_wav(uid, 2).write_bytes(b"RIFF")
        slot_ref_txt(uid, 2).write_text("orphan\n", encoding="utf-8")
        meta_path = user_voice_dir(uid) / SLOTS_META_NAME
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["slots"] = [s for s in data["slots"] if int(s["id"]) != 2]
        meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        slots = list_voice_slots(uid)
        slot2 = next(s for s in slots if s["id"] == 2)
        assert slot2["label"] == "목소리 2"
        assert slot2["hasReference"] is True

        new_slot = create_slot(uid, "새 슬롯")
        assert new_slot["id"] == 3


def main() -> int:
    test_list_voice_slots_is_read_only_on_meta()
    test_concurrent_list_and_label_updates()
    test_corrupt_meta_recovers_from_disk()
    test_orphan_disk_slot_visible_and_not_reused()
    print("OK: voice slots concurrency tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
