#!/usr/bin/env python3
"""Voice slot storage, migration, and limits."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from voice_slots import (
    MAX_VOICE_SLOTS,
    VoiceSlotError,
    create_slot,
    list_voice_slots,
    migrate_legacy_single_voice_to_slots,
    slot_has_reference,
    slot_ref_txt,
    slot_ref_wav,
    resolve_slot,
)
from user_storage import REF_TXT_NAME, REF_WAV_NAME, user_voice_dir


def test_legacy_migration_lossless() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 42
        voice = user_voice_dir(uid)
        voice.mkdir(parents=True)
        (voice / REF_WAV_NAME).write_bytes(b"RIFF")
        (voice / REF_TXT_NAME).write_text("hello script\n", encoding="utf-8")
        assert migrate_legacy_single_voice_to_slots(uid)
        assert not (voice / REF_WAV_NAME).exists()
        assert slot_has_reference(uid, 1)
        assert slot_ref_txt(uid, 1).read_text(encoding="utf-8").strip() == "hello script"
        assert not migrate_legacy_single_voice_to_slots(uid)


def test_slot_limit_fifth_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 7
        for i in range(MAX_VOICE_SLOTS):
            create_slot(uid, f"voice{i+1}")
        try:
            create_slot(uid, "one too many")
            raise AssertionError("expected slot_limit")
        except VoiceSlotError as exc:
            assert exc.code == "slot_limit"


def test_resolve_slot_requires_reference() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 3
        create_slot(uid, "empty")
        try:
            resolve_slot(uid, 1)
            raise AssertionError("expected missing reference")
        except VoiceSlotError as exc:
            assert exc.code == "missing_reference"


def main() -> int:
    test_legacy_migration_lossless()
    test_slot_limit_fifth_rejected()
    test_resolve_slot_requires_reference()
    print("OK: voice slot storage tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
