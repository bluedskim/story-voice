"""Per-user voice/audio paths and legacy migration."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def users_dir() -> Path:
    raw = os.environ.get("STORY_VOICE_USERS_DIR", "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "users"


USERS_DIR = users_dir()
LEGACY_VOICE_DIR = ROOT / "data" / "voice"
LEGACY_AUDIO_DIR = ROOT / "data" / "audio"
LEGACY_REF_WAV = LEGACY_VOICE_DIR / "reference.wav"
LEGACY_REF_TXT = LEGACY_VOICE_DIR / "reference.txt"

REF_WAV_NAME = "reference.wav"
REF_TXT_NAME = "reference.txt"


def user_root(user_id: int) -> Path:
    return users_dir() / str(user_id)


def user_voice_dir(user_id: int) -> Path:
    return user_root(user_id) / "voice"


def user_audio_dir(user_id: int) -> Path:
    return user_root(user_id) / "audio"


def user_ref_wav(user_id: int) -> Path:
    from voice_slots import ensure_slots_migrated, primary_slot_id, slot_ref_wav

    ensure_slots_migrated(user_id)
    return slot_ref_wav(user_id, primary_slot_id(user_id))


def user_ref_txt(user_id: int) -> Path:
    from voice_slots import ensure_slots_migrated, primary_slot_id, slot_ref_txt

    ensure_slots_migrated(user_id)
    return slot_ref_txt(user_id, primary_slot_id(user_id))


def user_story_audio(user_id: int, story_id: str) -> Path:
    return user_audio_dir(user_id) / f"{story_id}.m4a"


def user_voice_history_dir(user_id: int, slot_id: int = 1) -> Path:
    from voice_slots import slot_history_dir

    return slot_history_dir(user_id, slot_id)


def user_voice_pending_dir(user_id: int, slot_id: int = 1) -> Path:
    from voice_slots import slot_pending_dir

    return slot_pending_dir(user_id, slot_id)


def has_user_reference(user_id: int) -> bool:
    from voice_slots import ensure_slots_migrated, list_voice_slots

    ensure_slots_migrated(user_id)
    return any(s.get("hasReference") for s in list_voice_slots(user_id))


def user_reference_version(user_id: int) -> int | None:
    """Millisecond cache-bust token from primary slot reference.wav mtime."""
    from voice_slots import ensure_slots_migrated, primary_slot_id, slot_reference_version

    ensure_slots_migrated(user_id)
    return slot_reference_version(user_id, primary_slot_id(user_id))


def _legacy_voice_complete() -> bool:
    return LEGACY_REF_WAV.is_file() and LEGACY_REF_TXT.is_file()


def migrate_legacy_voice_for_admin(user_id: int) -> bool:
    """
    Copy legacy shared reference into an admin user's per-user voice dir once.
    Does not delete legacy files. Returns True if migration ran.
    """
    if has_user_reference(user_id):
        return False
    if not _legacy_voice_complete():
        return False
    from voice_slots import slot_dir, slot_ref_txt, slot_ref_wav

    voice_dir = user_voice_dir(user_id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    slot_dir(user_id, 1).mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_REF_WAV, slot_ref_wav(user_id, 1))
    shutil.copy2(LEGACY_REF_TXT, slot_ref_txt(user_id, 1))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = user_voice_history_dir(user_id, 1) / f"legacy-import-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_REF_WAV, backup_dir / REF_WAV_NAME)
    shutil.copy2(LEGACY_REF_TXT, backup_dir / REF_TXT_NAME)
    meta = {"importedAt": stamp, "source": "legacy_data_voice"}
    (backup_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8")
    from voice_slots import ensure_slot_meta_row, DEFAULT_SLOT_LABEL

    ensure_slot_meta_row(user_id, 1, DEFAULT_SLOT_LABEL)
    return True


def ensure_user_reference(user_id: int, is_admin: bool) -> tuple[Path, Path]:
    """Resolve primary reference wav/txt for generation; migrate legacy for admins on first use."""
    if is_admin:
        migrate_legacy_voice_for_admin(user_id)
    from voice_slots import ensure_slots_migrated, primary_slot_id, resolve_slot

    ensure_slots_migrated(user_id)
    if not has_user_reference(user_id):
        raise RuntimeError("목소리 샘플이 없어요. 먼저 목소리를 저장해 주세요.")
    return resolve_slot(user_id, primary_slot_id(user_id))
