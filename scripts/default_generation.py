"""Shared default (SYSTEM_USER_ID) multi-voice generation plans."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Callable

from default_narration import (
    DEFAULT_VOICE_IDS,
    DefaultReferenceUnavailable,
    LOCAL_ONLY_VOICES,
    ensure_default_reference,
    has_default_reference,
    local_only_reference_available,
    story_default_voice,
)
from member_generation import MemberGenerationPlan
from role_assignments import story_speaker_keys
from story_multivoice import story_markup_body_from_id
from voice_slots import NARRATOR_ROLE_KEY

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROLE_VOICES_PATH = ROOT / "content" / "default_role_voices.json"

log = logging.getLogger("story_voice.default_generation")

# When preferred narrator reference is missing; also used as last-resort generation order.
NARRATOR_FALLBACK_ORDER: tuple[str, ...] = ("dana", "harry", "anna")

ProgressCallback = Callable[[int, int, str], None]


@lru_cache(maxsize=1)
def _load_role_voice_maps() -> dict[str, dict[str, str]]:
    raw = json.loads(DEFAULT_ROLE_VOICES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("default_role_voices.json must be a story-id -> object map")
    out: dict[str, dict[str, str]] = {}
    for story_id, entry in raw.items():
        if not isinstance(entry, dict):
            raise RuntimeError(f"invalid entry for {story_id}")
        roles = entry.get("roles") or {}
        if not isinstance(roles, dict):
            raise RuntimeError(f"roles must be object for {story_id}")
        cleaned: dict[str, str] = {}
        for role, voice in roles.items():
            vid = str(voice).strip().lower()
            if vid not in DEFAULT_VOICE_IDS:
                raise RuntimeError(f"unsupported voice {voice!r} for {story_id} role {role}")
            cleaned[str(role)] = vid
        if len({story_default_voice(story_id), *cleaned.values()}) > 3:
            raise RuntimeError(f"more than 3 distinct default voices for {story_id}")
        out[str(story_id)] = cleaned
    return out


def role_voice_map_for_story(story_id: str) -> dict[str, str]:
    maps = _load_role_voice_maps()
    if story_id not in maps:
        raise KeyError(story_id)
    return dict(maps[story_id])


def _voice_reference_available(voice_id: str) -> bool:
    if voice_id in LOCAL_ONLY_VOICES:
        return local_only_reference_available(voice_id)
    return has_default_reference(voice_id)


def any_default_voice_reference_available() -> bool:
    return any(_voice_reference_available(v) for v in NARRATOR_FALLBACK_ORDER)


def resolve_narrator_voice(story_id: str) -> str:
    """Catalog narrator voice, or first available built-in in dana > harry > anna order."""
    preferred = story_default_voice(story_id)
    ordered: list[str] = []
    for v in (preferred, *NARRATOR_FALLBACK_ORDER):
        if v not in ordered:
            ordered.append(v)
    for voice_id in ordered:
        if _voice_reference_available(voice_id):
            if voice_id != preferred:
                log.warning(
                    "Default narrator voice %s unavailable for %s; using %s",
                    preferred,
                    story_id,
                    voice_id,
                )
            return voice_id
    raise DefaultReferenceUnavailable(
        preferred,
        story_id=story_id,
        detail="no built-in default voice reference available (dana, harry, anna)",
    )


def resolve_default_voice_reference(
    voice_id: str,
    *,
    story_id: str,
    narrator_voice: str,
) -> tuple[Path, Path]:
    """Built-in voice wav/txt; missing non-narrator voices fall back to narrator refs."""
    voice_id = voice_id.strip().lower()
    if not _voice_reference_available(voice_id):
        if voice_id == narrator_voice:
            raise DefaultReferenceUnavailable(voice_id, story_id=story_id)
        log.warning(
            "Default role voice %s missing for %s; falling back to narrator voice %s",
            voice_id,
            story_id,
            narrator_voice,
        )
        voice_id = narrator_voice
    try:
        return ensure_default_reference(voice_id)
    except DefaultReferenceUnavailable:
        if voice_id == narrator_voice:
            raise
        log.warning(
            "Default role voice %s unavailable for %s; falling back to narrator voice %s",
            voice_id,
            story_id,
            narrator_voice,
        )
        return ensure_default_reference(narrator_voice)


def effective_voice_for_role(
    role_key: str | None,
    *,
    story_id: str,
    narrator_voice: str,
    role_map: dict[str, str],
) -> str:
    if role_key is None or role_key == NARRATOR_ROLE_KEY:
        return narrator_voice
    voice = role_map.get(role_key, narrator_voice)
    if voice not in DEFAULT_VOICE_IDS:
        return narrator_voice
    if not _voice_reference_available(voice):
        log.warning(
            "Mapped voice %s for role %s (%s) unavailable; using narrator %s",
            voice,
            role_key,
            story_id,
            narrator_voice,
        )
        return narrator_voice
    return voice


def build_default_generation_plan(story_id: str) -> MemberGenerationPlan:
    """Resolve built-in references for narrator + mapped roles (max 3 voices)."""
    markup = story_markup_body_from_id(story_id)
    role_map = role_voice_map_for_story(story_id)
    narrator_voice = resolve_narrator_voice(story_id)

    voice_for_slot: dict[str, int] = {}
    slot_refs: dict[int, tuple[Path, Path]] = {}
    assignments: dict[str, int] = {}
    next_slot = 1

    def slot_for_voice(voice_id: str) -> int:
        nonlocal next_slot
        if voice_id not in voice_for_slot:
            if len(voice_for_slot) >= 3:
                raise RuntimeError(f"more than 3 default voices required for {story_id}")
            voice_for_slot[voice_id] = next_slot
            slot_refs[next_slot] = resolve_default_voice_reference(
                voice_id,
                story_id=story_id,
                narrator_voice=narrator_voice,
            )
            next_slot += 1
        return voice_for_slot[voice_id]

    assignments[NARRATOR_ROLE_KEY] = slot_for_voice(narrator_voice)

    for role_key in story_speaker_keys(markup):
        voice = effective_voice_for_role(
            role_key,
            story_id=story_id,
            narrator_voice=narrator_voice,
            role_map=role_map,
        )
        assignments[role_key] = slot_for_voice(voice)

    multivoice = len(voice_for_slot) > 1 and bool(story_speaker_keys(markup))

    return MemberGenerationPlan(
        story_id=story_id,
        markup_body=markup,
        multivoice=multivoice,
        assignments=assignments,
        slot_refs=slot_refs,
    )


def generate_default_story(
    backend,
    story_id: str,
    story_text_stripped: str,
    output_path: Path,
    on_progress: ProgressCallback,
    *,
    verify_asr: bool = False,
) -> None:
    plan = build_default_generation_plan(story_id)
    backend.generate_default_story(
        plan,
        story_text_stripped,
        output_path,
        on_progress,
        verify_asr=verify_asr,
    )