"""Per-member voice slots (up to 4) with legacy single-voice migration."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from user_storage import (
    REF_TXT_NAME,
    REF_WAV_NAME,
    USERS_DIR,
    user_root,
    user_voice_dir,
)

MAX_VOICE_SLOTS = 4
DEFAULT_SLOT_LABEL = "내 목소리"
NARRATOR_ROLE_KEY = "narrator"

SLOTS_META_NAME = "slots.json"
SLOTS_DIR_NAME = "slots"


class VoiceSlotError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _slots_meta_path(user_id: int) -> Path:
    return user_voice_dir(user_id) / SLOTS_META_NAME


def _slots_root(user_id: int) -> Path:
    return user_voice_dir(user_id) / SLOTS_DIR_NAME


def slot_dir(user_id: int, slot_id: int) -> Path:
    return _slots_root(user_id) / str(slot_id)


def slot_ref_wav(user_id: int, slot_id: int) -> Path:
    return slot_dir(user_id, slot_id) / REF_WAV_NAME


def slot_ref_txt(user_id: int, slot_id: int) -> Path:
    return slot_dir(user_id, slot_id) / REF_TXT_NAME


def slot_history_dir(user_id: int, slot_id: int) -> Path:
    return slot_dir(user_id, slot_id) / "history"


def slot_pending_dir(user_id: int, slot_id: int) -> Path:
    return slot_dir(user_id, slot_id) / "pending"


def _legacy_ref_wav(user_id: int) -> Path:
    return user_voice_dir(user_id) / REF_WAV_NAME


def _legacy_ref_txt(user_id: int) -> Path:
    return user_voice_dir(user_id) / REF_TXT_NAME


def _legacy_pending_dir(user_id: int) -> Path:
    return user_voice_dir(user_id) / "pending"


def _legacy_history_dir(user_id: int) -> Path:
    return user_voice_dir(user_id) / "history"


def slot_has_reference(user_id: int, slot_id: int) -> bool:
    return slot_ref_wav(user_id, slot_id).is_file() and slot_ref_txt(user_id, slot_id).is_file()


def slot_reference_version(user_id: int, slot_id: int) -> int | None:
    wav = slot_ref_wav(user_id, slot_id)
    if not wav.is_file():
        return None
    return int(wav.stat().st_mtime * 1000)


def _read_slots_meta(user_id: int) -> list[dict]:
    path = _slots_meta_path(user_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        slots = data.get("slots")
        if isinstance(slots, list):
            return [s for s in slots if isinstance(s, dict)]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _write_slots_meta(user_id: int, slots: list[dict]) -> None:
    voice_dir = user_voice_dir(user_id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    payload = {"slots": slots}
    _slots_meta_path(user_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def migrate_legacy_single_voice_to_slots(user_id: int) -> bool:
    """
    Move data/users/<id>/voice/reference.wav|.txt (+ pending/history) into slot 1.
    Returns True if migration ran.
    """
    if slot_has_reference(user_id, 1):
        _ensure_slot_meta_row(user_id, 1, DEFAULT_SLOT_LABEL)
        return False
    legacy_wav = _legacy_ref_wav(user_id)
    legacy_txt = _legacy_ref_txt(user_id)
    if not legacy_wav.is_file() or not legacy_txt.is_file():
        return False

    dest = slot_dir(user_id, 1)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy_wav), str(slot_ref_wav(user_id, 1)))
    shutil.move(str(legacy_txt), str(slot_ref_txt(user_id, 1)))

    leg_pending = _legacy_pending_dir(user_id)
    if leg_pending.is_dir() and any(leg_pending.iterdir()):
        slot_pending = slot_pending_dir(user_id, 1)
        slot_pending.mkdir(parents=True, exist_ok=True)
        for child in leg_pending.iterdir():
            target = slot_pending / child.name
            if target.exists():
                continue
            shutil.move(str(child), str(target))
        try:
            leg_pending.rmdir()
        except OSError:
            pass

    leg_hist = _legacy_history_dir(user_id)
    if leg_hist.is_dir() and any(leg_hist.iterdir()):
        slot_hist = slot_history_dir(user_id, 1)
        slot_hist.mkdir(parents=True, exist_ok=True)
        for child in leg_hist.iterdir():
            target = slot_hist / child.name
            if target.exists():
                continue
            shutil.move(str(child), str(target))
        try:
            leg_hist.rmdir()
        except OSError:
            pass

    _ensure_slot_meta_row(user_id, 1, DEFAULT_SLOT_LABEL)
    return True


def ensure_slot_meta_row(user_id: int, slot_id: int, label: str) -> None:
    slots = _read_slots_meta(user_id)
    by_id = {int(s.get("id", 0)): s for s in slots if s.get("id") is not None}
    if slot_id not in by_id:
        by_id[slot_id] = {
            "id": slot_id,
            "label": label,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    ordered = [by_id[i] for i in sorted(by_id.keys()) if 1 <= i <= MAX_VOICE_SLOTS]
    _write_slots_meta(user_id, ordered)


def _ensure_slot_meta_row(user_id: int, slot_id: int, label: str) -> None:
    ensure_slot_meta_row(user_id, slot_id, label)


def ensure_slots_migrated(user_id: int) -> None:
    migrate_legacy_single_voice_to_slots(user_id)


def list_voice_slots(user_id: int) -> list[dict]:
    ensure_slots_migrated(user_id)
    meta = _read_slots_meta(user_id)
    out: list[dict] = []
    for row in sorted(meta, key=lambda s: int(s.get("id", 999))):
        sid = int(row.get("id", 0))
        if sid < 1 or sid > MAX_VOICE_SLOTS:
            continue
        label = str(row.get("label") or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
        has_ref = slot_has_reference(user_id, sid)
        entry = {
            "id": sid,
            "label": label,
            "hasReference": has_ref,
        }
        if has_ref:
            entry["referenceVersion"] = slot_reference_version(user_id, sid)
        out.append(entry)
    if not out and slot_has_reference(user_id, 1):
        out.append(
            {
                "id": 1,
                "label": DEFAULT_SLOT_LABEL,
                "hasReference": True,
                "referenceVersion": slot_reference_version(user_id, 1),
            }
        )
    return out


def count_filled_slots(user_id: int) -> int:
    return sum(1 for s in list_voice_slots(user_id) if s.get("hasReference"))


def next_empty_slot_id(user_id: int) -> int | None:
    ensure_slots_migrated(user_id)
    used = {s["id"] for s in list_voice_slots(user_id)}
    for i in range(1, MAX_VOICE_SLOTS + 1):
        if i not in used or not slot_has_reference(user_id, i):
            if not slot_has_reference(user_id, i):
                return i
    return None


def create_slot(user_id: int, label: str) -> dict:
    ensure_slots_migrated(user_id)
    label = (label or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
    slots = list_voice_slots(user_id)
    defined_ids = {s["id"] for s in slots}
    if len(defined_ids) >= MAX_VOICE_SLOTS:
        raise VoiceSlotError(
            f"목소리는 최대 {MAX_VOICE_SLOTS}개까지 저장할 수 있어요.",
            "slot_limit",
        )
    slot_id = None
    for i in range(1, MAX_VOICE_SLOTS + 1):
        if i not in defined_ids:
            slot_id = i
            break
    if slot_id is None:
        raise VoiceSlotError(
            f"목소리는 최대 {MAX_VOICE_SLOTS}개까지 저장할 수 있어요.",
            "slot_limit",
        )
    _ensure_slot_meta_row(user_id, slot_id, label)
    slot_dir(user_id, slot_id).mkdir(parents=True, exist_ok=True)
    return {"id": slot_id, "label": label, "hasReference": False}


def update_slot_label(user_id: int, slot_id: int, label: str) -> dict:
    if slot_id < 1 or slot_id > MAX_VOICE_SLOTS:
        raise VoiceSlotError("잘못된 목소리 번호예요.", "invalid_slot")
    label = (label or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
    slots = _read_slots_meta(user_id)
    found = False
    for row in slots:
        if int(row.get("id", 0)) == slot_id:
            row["label"] = label
            found = True
            break
    if not found:
        _ensure_slot_meta_row(user_id, slot_id, label)
    else:
        _write_slots_meta(user_id, slots)
    return {
        "id": slot_id,
        "label": label,
        "hasReference": slot_has_reference(user_id, slot_id),
        "referenceVersion": slot_reference_version(user_id, slot_id),
    }


def resolve_slot(user_id: int, slot_id: int) -> tuple[Path, Path]:
    ensure_slots_migrated(user_id)
    if slot_id < 1 or slot_id > MAX_VOICE_SLOTS:
        raise VoiceSlotError("잘못된 목소리 번호예요.", "invalid_slot")
    if not slot_has_reference(user_id, slot_id):
        raise VoiceSlotError("해당 목소리 슬롯에 저장된 녹음이 없어요.", "missing_reference")
    return slot_ref_wav(user_id, slot_id), slot_ref_txt(user_id, slot_id)


def primary_slot_id(user_id: int) -> int:
    ensure_slots_migrated(user_id)
    if slot_has_reference(user_id, 1):
        return 1
    for s in list_voice_slots(user_id):
        if s.get("hasReference"):
            return int(s["id"])
    return 1
