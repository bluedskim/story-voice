"""Per-member voice slots (up to 4) with legacy single-voice migration."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
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
MAX_SLOT_LABEL_LEN = 20
DEFAULT_SLOT_LABEL = "내 목소리"
NARRATOR_ROLE_KEY = "narrator"
DISK_RECOVERED_LABEL_PREFIX = "목소리"

SLOTS_META_NAME = "slots.json"
SLOTS_DIR_NAME = "slots"

log = logging.getLogger("story_voice.voice_slots")

_user_locks: dict[int, threading.RLock] = {}
_user_locks_guard = threading.Lock()


class VoiceSlotError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _user_lock(user_id: int) -> threading.RLock:
    with _user_locks_guard:
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = threading.RLock()
            _user_locks[user_id] = lock
        return lock


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


def _slot_occupied_on_disk(user_id: int, slot_id: int) -> bool:
    return slot_ref_wav(user_id, slot_id).is_file() or slot_ref_txt(user_id, slot_id).is_file()


def _default_recovered_label(slot_id: int) -> str:
    return f"{DISK_RECOVERED_LABEL_PREFIX} {slot_id}"


def _normalize_slots_rows(slots: list[dict]) -> list[dict]:
    by_id: dict[int, dict] = {}
    for row in slots:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id")
        if raw_id is None:
            continue
        try:
            sid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if sid < 1 or sid > MAX_VOICE_SLOTS:
            continue
        label = str(row.get("label") or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
        created = row.get("createdAt")
        if not isinstance(created, str) or not created.strip():
            created = datetime.now(timezone.utc).isoformat()
        by_id[sid] = {"id": sid, "label": label, "createdAt": created}
    return [by_id[i] for i in sorted(by_id.keys())]


def _serialize_slots_meta(slots: list[dict]) -> str:
    ordered = _normalize_slots_rows(slots)
    payload = {"slots": ordered}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _backup_corrupt_slots_meta(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        shutil.copy2(path, backup)
        return backup
    except OSError as exc:
        log.warning("voice slots: failed to backup corrupt %s: %s", path, exc)
        return None


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    tmp = path.with_name(tmp_name)
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_slots_meta(user_id: int, slots: list[dict]) -> bool:
    """Persist slot metadata if content changed. Returns True if file was written."""
    path = _slots_meta_path(user_id)
    new_content = _serialize_slots_meta(slots)
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
            if existing == new_content:
                return False
        except OSError as exc:
            log.warning("voice slots: could not read %s for compare: %s", path, exc)
    _atomic_write_text(path, new_content)
    return True


def _recover_slots_meta_from_disk(user_id: int) -> list[dict]:
    rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for sid in range(1, MAX_VOICE_SLOTS + 1):
        if _slot_occupied_on_disk(user_id, sid):
            rows.append(
                {
                    "id": sid,
                    "label": _default_recovered_label(sid),
                    "createdAt": now,
                }
            )
    return rows


def _read_slots_meta_file(user_id: int) -> tuple[list[dict] | None, str | None]:
    """
    Read slots.json without recovery writes.
    Returns (slots, None) on success; (None, reason) when file is missing, empty, or invalid.
    """
    path = _slots_meta_path(user_id)
    if not path.is_file():
        return [], None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("voice slots: read failed for user %s: %s", user_id, exc)
        return None, "read_error"
    if not raw.strip():
        log.warning("voice slots: empty slots.json for user %s", user_id)
        return None, "empty"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("voice slots: invalid JSON for user %s: %s", user_id, exc)
        return None, "json_error"
    slots = data.get("slots")
    if not isinstance(slots, list):
        log.warning("voice slots: missing slots array for user %s", user_id)
        return None, "invalid_shape"
    return _normalize_slots_rows([s for s in slots if isinstance(s, dict)]), None


def _load_slots_meta(user_id: int, *, allow_recovery_write: bool = True) -> list[dict]:
    rows, err = _read_slots_meta_file(user_id)
    if err is None:
        return rows or []
    path = _slots_meta_path(user_id)
    if path.is_file():
        backup = _backup_corrupt_slots_meta(path)
        if backup:
            log.info(
                "voice slots: backed up corrupt meta for user %s to %s",
                user_id,
                backup.name,
            )
    recovered = _recover_slots_meta_from_disk(user_id)
    if allow_recovery_write and recovered:
        _write_slots_meta(user_id, recovered)
    return recovered


def migrate_legacy_single_voice_to_slots(user_id: int) -> bool:
    """
    Move data/users/<id>/voice/reference.wav|.txt (+ pending/history) into slot 1.
    Returns True if migration ran.
    """
    with _user_lock(user_id):
        return _migrate_legacy_single_voice_to_slots_unlocked(user_id)


def _migrate_legacy_single_voice_to_slots_unlocked(user_id: int) -> bool:
    if slot_has_reference(user_id, 1):
        meta = _load_slots_meta(user_id, allow_recovery_write=False)
        if not any(int(s.get("id", 0)) == 1 for s in meta):
            _ensure_slot_meta_row_unlocked(user_id, 1, DEFAULT_SLOT_LABEL)
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

    _ensure_slot_meta_row_unlocked(user_id, 1, DEFAULT_SLOT_LABEL)
    return True


def _ensure_slot_meta_row_unlocked(user_id: int, slot_id: int, label: str) -> None:
    slots = _load_slots_meta(user_id, allow_recovery_write=False)
    by_id = {int(s["id"]): s for s in slots}
    label = (label or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
    if slot_id in by_id and by_id[slot_id].get("label") == label:
        return
    if slot_id not in by_id:
        by_id[slot_id] = {
            "id": slot_id,
            "label": label,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    else:
        by_id[slot_id]["label"] = label
    ordered = [by_id[i] for i in sorted(by_id.keys()) if 1 <= i <= MAX_VOICE_SLOTS]
    _write_slots_meta(user_id, ordered)


def ensure_slot_meta_row(user_id: int, slot_id: int, label: str) -> None:
    with _user_lock(user_id):
        _ensure_slot_meta_row_unlocked(user_id, slot_id, label)


def _ensure_slot_meta_row(user_id: int, slot_id: int, label: str) -> None:
    ensure_slot_meta_row(user_id, slot_id, label)


def ensure_slots_migrated(user_id: int) -> None:
    with _user_lock(user_id):
        _migrate_legacy_single_voice_to_slots_unlocked(user_id)


def _collect_slot_ids_for_list(user_id: int, meta: list[dict]) -> list[int]:
    ids: set[int] = set()
    for row in meta:
        try:
            sid = int(row.get("id", 0))
        except (TypeError, ValueError):
            continue
        if 1 <= sid <= MAX_VOICE_SLOTS:
            ids.add(sid)
    for sid in range(1, MAX_VOICE_SLOTS + 1):
        if _slot_occupied_on_disk(user_id, sid):
            ids.add(sid)
    return sorted(ids)


def list_voice_slots(user_id: int) -> list[dict]:
    with _user_lock(user_id):
        _migrate_legacy_single_voice_to_slots_unlocked(user_id)
        meta = _load_slots_meta(user_id, allow_recovery_write=True)
        meta_by_id = {int(s["id"]): s for s in meta}
        out: list[dict] = []
        for sid in _collect_slot_ids_for_list(user_id, meta):
            row = meta_by_id.get(sid)
            if row:
                label = str(row.get("label") or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
            elif _slot_occupied_on_disk(user_id, sid):
                label = _default_recovered_label(sid)
            else:
                label = DEFAULT_SLOT_LABEL
            has_ref = slot_has_reference(user_id, sid)
            entry: dict = {
                "id": sid,
                "label": label,
                "hasReference": has_ref,
            }
            if has_ref:
                entry["referenceVersion"] = slot_reference_version(user_id, sid)
            out.append(entry)
        return out


def count_filled_slots(user_id: int) -> int:
    return sum(1 for s in list_voice_slots(user_id) if s.get("hasReference"))


def next_empty_slot_id(user_id: int) -> int | None:
    with _user_lock(user_id):
        _migrate_legacy_single_voice_to_slots_unlocked(user_id)
        used = {s["id"] for s in _list_voice_slots_unlocked(user_id)}
        for i in range(1, MAX_VOICE_SLOTS + 1):
            if _slot_occupied_on_disk(user_id, i) or slot_has_reference(user_id, i):
                continue
            if i not in used:
                return i
        return None


def _list_voice_slots_unlocked(user_id: int, meta: list[dict] | None = None) -> list[dict]:
    if meta is None:
        meta = _load_slots_meta(user_id, allow_recovery_write=False)
    meta_by_id = {int(s["id"]): s for s in meta}
    out: list[dict] = []
    for sid in _collect_slot_ids_for_list(user_id, meta):
        row = meta_by_id.get(sid)
        if row:
            label = str(row.get("label") or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
        elif _slot_occupied_on_disk(user_id, sid):
            label = _default_recovered_label(sid)
        else:
            label = DEFAULT_SLOT_LABEL
        has_ref = slot_has_reference(user_id, sid)
        entry: dict = {
            "id": sid,
            "label": label,
            "hasReference": has_ref,
        }
        if has_ref:
            entry["referenceVersion"] = slot_reference_version(user_id, sid)
        out.append(entry)
    return out


def create_slot(user_id: int, label: str) -> dict:
    with _user_lock(user_id):
        _migrate_legacy_single_voice_to_slots_unlocked(user_id)
        label = (label or DEFAULT_SLOT_LABEL).strip() or DEFAULT_SLOT_LABEL
        slots = _list_voice_slots_unlocked(user_id)
        defined_ids = {s["id"] for s in slots}
        if len(defined_ids) >= MAX_VOICE_SLOTS:
            raise VoiceSlotError(
                f"목소리는 최대 {MAX_VOICE_SLOTS}개까지 저장할 수 있어요.",
                "slot_limit",
            )
        slot_id = None
        for i in range(1, MAX_VOICE_SLOTS + 1):
            if _slot_occupied_on_disk(user_id, i):
                continue
            if i not in defined_ids:
                slot_id = i
                break
        if slot_id is None:
            raise VoiceSlotError(
                f"목소리는 최대 {MAX_VOICE_SLOTS}개까지 저장할 수 있어요.",
                "slot_limit",
            )
        _ensure_slot_meta_row_unlocked(user_id, slot_id, label)
        slot_dir(user_id, slot_id).mkdir(parents=True, exist_ok=True)
        return {"id": slot_id, "label": label, "hasReference": False}


def _user_has_slot_unlocked(user_id: int, slot_id: int, meta: list[dict]) -> bool:
    if any(int(s.get("id", 0)) == slot_id for s in meta):
        return True
    return _slot_occupied_on_disk(user_id, slot_id)


def _validate_slot_label(label: str) -> str:
    cleaned = (label or "").strip()
    if not cleaned:
        raise VoiceSlotError("이름을 입력해 주세요.", "empty_label")
    if len(cleaned) > MAX_SLOT_LABEL_LEN:
        raise VoiceSlotError(
            f"이름은 {MAX_SLOT_LABEL_LEN}자 이하여야 해요.",
            "label_too_long",
        )
    return cleaned


def update_slot_label(user_id: int, slot_id: int, label: str) -> list[dict]:
    if slot_id < 1 or slot_id > MAX_VOICE_SLOTS:
        raise VoiceSlotError("잘못된 목소리 번호예요.", "invalid_slot")
    label = _validate_slot_label(label)
    with _user_lock(user_id):
        _migrate_legacy_single_voice_to_slots_unlocked(user_id)
        meta = _load_slots_meta(user_id, allow_recovery_write=False)
        if not _user_has_slot_unlocked(user_id, slot_id, meta):
            raise VoiceSlotError("해당 목소리를 찾을 수 없어요.", "unknown_slot")
        updated = False
        for row in meta:
            if int(row.get("id", 0)) == slot_id:
                if row.get("label") != label:
                    row["label"] = label
                    _write_slots_meta(user_id, meta)
                updated = True
                break
        if not updated:
            _ensure_slot_meta_row_unlocked(user_id, slot_id, label)
        return _list_voice_slots_unlocked(user_id)


def resolve_slot(user_id: int, slot_id: int) -> tuple[Path, Path]:
    with _user_lock(user_id):
        _migrate_legacy_single_voice_to_slots_unlocked(user_id)
        if slot_id < 1 or slot_id > MAX_VOICE_SLOTS:
            raise VoiceSlotError("잘못된 목소리 번호예요.", "invalid_slot")
        if not slot_has_reference(user_id, slot_id):
            raise VoiceSlotError("해당 목소리 슬롯에 저장된 녹음이 없어요.", "missing_reference")
        return slot_ref_wav(user_id, slot_id), slot_ref_txt(user_id, slot_id)


def primary_slot_id(user_id: int) -> int:
    with _user_lock(user_id):
        _migrate_legacy_single_voice_to_slots_unlocked(user_id)
        if slot_has_reference(user_id, 1):
            return 1
        for s in _list_voice_slots_unlocked(user_id):
            if s.get("hasReference"):
                return int(s["id"])
        return 1
