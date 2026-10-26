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
    return user_voice_dir(user_id) / REF_WAV_NAME


def user_ref_txt(user_id: int) -> Path:
    return user_voice_dir(user_id) / REF_TXT_NAME


def user_story_audio(user_id: int, story_id: str) -> Path:
    return user_audio_dir(user_id) / f"{story_id}.m4a"


def user_voice_history_dir(user_id: int) -> Path:
    return user_voice_dir(user_id) / "history"


def user_voice_pending_dir(user_id: int) -> Path:
    return user_voice_dir(user_id) / "pending"


def has_user_reference(user_id: int) -> bool:
    return user_ref_wav(user_id).is_file() and user_ref_txt(user_id).is_file()


def user_reference_version(user_id: int) -> int | None:
    """Millisecond cache-bust token from reference.wav mtime (None if missing)."""
    wav = user_ref_wav(user_id)
    if not wav.is_file():
        return None
    return int(wav.stat().st_mtime * 1000)


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
    voice_dir = user_voice_dir(user_id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_REF_WAV, user_ref_wav(user_id))
    shutil.copy2(LEGACY_REF_TXT, user_ref_txt(user_id))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = user_voice_history_dir(user_id) / f"legacy-import-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_REF_WAV, backup_dir / REF_WAV_NAME)
    shutil.copy2(LEGACY_REF_TXT, backup_dir / REF_TXT_NAME)
    meta = {"importedAt": stamp, "source": "legacy_data_voice"}
    (backup_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def ensure_user_reference(user_id: int, is_admin: bool) -> tuple[Path, Path]:
    """Resolve reference wav/txt for generation; migrate legacy for admins on first use."""
    if is_admin:
        migrate_legacy_voice_for_admin(user_id)
    if not has_user_reference(user_id):
        raise RuntimeError("목소리 샘플이 없어요. 먼저 목소리를 저장해 주세요.")
    return user_ref_wav(user_id), user_ref_txt(user_id)
