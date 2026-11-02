"""Per-member story role → voice slot assignments."""

from __future__ import annotations

import json
import re
from pathlib import Path

from story_speaker_markup import iter_tagged_lines
from voice_slots import NARRATOR_ROLE_KEY, ensure_slots_migrated, slot_has_reference, slot_reference_version

STORY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NARRATOR_LABEL = "낭독자"


class RoleAssignmentError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _assignments_dir(user_id: int) -> Path:
    from user_storage import user_root

    return user_root(user_id) / "story_roles"


def _assignment_path(user_id: int, story_id: str) -> Path:
    if not STORY_ID_RE.match(story_id):
        raise RoleAssignmentError("잘못된 이야기 id", "invalid_story")
    return _assignments_dir(user_id) / f"{story_id}.json"


def story_speaker_keys(story_markup_body: str) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for key, _content in iter_tagged_lines(story_markup_body):
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def story_roles(story_markup_body: str) -> list[dict]:
    """Roles shown in UI: narrator + distinct @speaker keys."""
    roles = [{"key": NARRATOR_ROLE_KEY, "label": NARRATOR_LABEL}]
    for key in story_speaker_keys(story_markup_body):
        roles.append({"key": key, "label": key})
    return roles


def _load_raw(user_id: int, story_id: str) -> dict | None:
    path = _assignment_path(user_id, story_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def load_assignment(user_id: int, story_id: str) -> dict:
    ensure_slots_migrated(user_id)
    raw = _load_raw(user_id, story_id)
    assignments = {}
    slot_versions: dict[str, int] = {}
    if raw:
        a = raw.get("assignments")
        if isinstance(a, dict):
            assignments = {str(k): int(v) for k, v in a.items() if v is not None}
        sv = raw.get("slotVersions")
        if isinstance(sv, dict):
            slot_versions = {str(k): int(v) for k, v in sv.items()}

    valid, issues = validate_assignment(user_id, story_id, assignments, slot_versions)
    return {
        "assignments": assignments,
        "slotVersions": slot_versions,
        "valid": valid,
        "issues": issues,
    }


def validate_assignment(
    user_id: int,
    story_id: str,
    assignments: dict[str, int],
    slot_versions: dict[str, int],
) -> tuple[bool, list[str]]:
    from story_multivoice import story_markup_body_from_id

    issues: list[str] = []
    try:
        markup = story_markup_body_from_id(story_id)
    except KeyError:
        return False, ["unknown_story"]

    role_keys = {r["key"] for r in story_roles(markup)}
    narrator_slot = assignments.get(NARRATOR_ROLE_KEY) or primary_narrator_slot(user_id)

    for role_key, slot_id in assignments.items():
        if role_key not in role_keys:
            issues.append(f"unknown_role:{role_key}")
            continue
        if slot_id < 1 or slot_id > 4:
            issues.append(f"invalid_slot:{role_key}")
            continue
        if not slot_has_reference(user_id, slot_id):
            issues.append(f"missing_slot:{role_key}")
            continue
        expected_ver = slot_reference_version(user_id, slot_id)
        stored_ver = slot_versions.get(str(slot_id))
        if stored_ver is not None and expected_ver is not None and stored_ver != expected_ver:
            issues.append(f"stale_slot:{role_key}")

    if narrator_slot and not slot_has_reference(user_id, narrator_slot):
        issues.append("missing_narrator")

    return len(issues) == 0, issues


def primary_narrator_slot(user_id: int) -> int:
    from voice_slots import list_voice_slots, primary_slot_id

    ensure_slots_migrated(user_id)
    return primary_slot_id(user_id)


def save_assignment(user_id: int, story_id: str, assignments: dict[str, int]) -> dict:
    from story_multivoice import story_markup_body_from_id

    ensure_slots_migrated(user_id)
    try:
        markup = story_markup_body_from_id(story_id)
    except KeyError as exc:
        raise RoleAssignmentError("이야기를 찾을 수 없어요.", "unknown_story") from exc

    role_keys = {r["key"] for r in story_roles(markup)}
    cleaned: dict[str, int] = {}
    for key, slot_id in assignments.items():
        if key not in role_keys:
            raise RoleAssignmentError(f"알 수 없는 역할이에요: {key}", "unknown_role")
        sid = int(slot_id)
        if sid < 1 or sid > 4:
            raise RoleAssignmentError("잘못된 목소리 번호예요.", "invalid_slot")
        if not slot_has_reference(user_id, sid):
            raise RoleAssignmentError("선택한 목소리가 없어요. 목소리 탭에서 먼저 저장해 주세요.", "missing_slot")
        cleaned[key] = sid

    if NARRATOR_ROLE_KEY not in cleaned:
        cleaned[NARRATOR_ROLE_KEY] = primary_narrator_slot(user_id)

    slot_versions: dict[str, int] = {}
    used_slots = set(cleaned.values())
    for sid in used_slots:
        ver = slot_reference_version(user_id, sid)
        if ver is not None:
            slot_versions[str(sid)] = ver

    valid, issues = validate_assignment(user_id, story_id, cleaned, slot_versions)
    if not valid:
        raise RoleAssignmentError("역할 배정을 확인할 수 없어요.", "invalid_assignment")

    path = _assignment_path(user_id, story_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"assignments": cleaned, "slotVersions": slot_versions}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return load_assignment(user_id, story_id)


def resolved_slot_for_role(
    user_id: int,
    story_id: str,
    role_key: str | None,
    assignments: dict[str, int] | None = None,
) -> int:
    """Unassigned speaker roles fall back to narrator slot."""
    if assignments is None:
        loaded = load_assignment(user_id, story_id)
        assignments = loaded.get("assignments") or {}
    narrator = assignments.get(NARRATOR_ROLE_KEY) or primary_narrator_slot(user_id)
    if role_key is None or role_key == NARRATOR_ROLE_KEY:
        return narrator
    return assignments.get(role_key, narrator)


def needs_multivoice_generation(user_id: int, story_id: str, assignments: dict[str, int]) -> bool:
    """True when more than one distinct slot is used for this story."""
    from story_multivoice import story_markup_body_from_id

    try:
        markup = story_markup_body_from_id(story_id)
    except KeyError:
        return False
    if not story_speaker_keys(markup):
        return False
    slots_used: set[int] = set()
    for role in story_roles(markup):
        sid = resolved_slot_for_role(user_id, story_id, role["key"], assignments)
        slots_used.add(sid)
    return len(slots_used) > 1


def invalidate_if_stale(user_id: int, story_id: str) -> bool:
    """Clear assignment file when slot versions no longer match. Returns True if cleared."""
    raw = _load_raw(user_id, story_id)
    if not raw:
        return False
    a = raw.get("assignments") or {}
    sv = raw.get("slotVersions") or {}
    if not isinstance(a, dict):
        return False
    assignments = {str(k): int(v) for k, v in a.items()}
    slot_versions = {str(k): int(v) for k, v in sv.items()} if isinstance(sv, dict) else {}
    valid, _ = validate_assignment(user_id, story_id, assignments, slot_versions)
    if valid:
        return False
    path = _assignment_path(user_id, story_id)
    path.unlink(missing_ok=True)
    return True
