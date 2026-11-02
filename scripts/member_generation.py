"""Member story generation: single-voice vs multivoice with role assignments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class MemberGenerationPlan:
    story_id: str
    markup_body: str
    multivoice: bool
    assignments: dict[str, int]
    slot_refs: dict[int, tuple[Path, Path]]


def build_member_generation_plan(user_id: int, story_id: str) -> MemberGenerationPlan:
    from role_assignments import (
        invalidate_if_stale,
        load_assignment,
        needs_multivoice_generation,
        primary_narrator_slot,
    )
    from story_multivoice import story_markup_body_from_id
    from voice_slots import list_voice_slots, resolve_slot

    markup = story_markup_body_from_id(story_id)
    invalidate_if_stale(user_id, story_id)
    loaded = load_assignment(user_id, story_id)
    assignments = dict(loaded.get("assignments") or {})
    if not assignments:
        assignments = {"narrator": primary_narrator_slot(user_id)}

    multivoice = needs_multivoice_generation(user_id, story_id, assignments)
    if not multivoice:
        # Single reference path — use stripped text equivalent via markup (speaker tags ignored)
        narrator = assignments.get("narrator") or primary_narrator_slot(user_id)
        wav, txt = resolve_slot(user_id, narrator)
        return MemberGenerationPlan(
            story_id=story_id,
            markup_body=markup,
            multivoice=False,
            assignments=assignments,
            slot_refs={narrator: (wav, txt)},
        )

    slots_needed: set[int] = set(assignments.values())
    from role_assignments import resolved_slot_for_role, story_roles

    for role in story_roles(markup):
        slots_needed.add(resolved_slot_for_role(user_id, story_id, role["key"], assignments))

    slot_refs: dict[int, tuple[Path, Path]] = {}
    for sid in sorted(slots_needed):
        slot_refs[sid] = resolve_slot(user_id, sid)

    return MemberGenerationPlan(
        story_id=story_id,
        markup_body=markup,
        multivoice=True,
        assignments=assignments,
        slot_refs=slot_refs,
    )


def generate_member_story(
    backend,
    user_id: int,
    story_id: str,
    story_text_stripped: str,
    output_path: Path,
    on_progress: ProgressCallback,
    *,
    verify_asr: bool = False,
) -> None:
    plan = build_member_generation_plan(user_id, story_id)
    backend.generate_member_story(
        plan,
        story_text_stripped,
        output_path,
        on_progress,
        verify_asr=verify_asr,
    )
