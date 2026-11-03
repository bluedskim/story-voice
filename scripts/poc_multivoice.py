#!/usr/bin/env python3
"""PoC: render one catalog story with per-speaker voice references (single process, one --out file)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_story import DEFAULT_MAX_CHARS, DEFAULT_MODEL, StoryGenerator, load_ref_text
from story_multivoice import (
    build_voice_resolver,
    cache_voice_references,
    load_voice_reference,
    narrate_story_multivoice,
    parse_ref_arg,
    story_markup_body_from_id,
)


def _parse_map_items(raw_maps: list[str]) -> dict[str, tuple[Path, Path | None]]:
    out: dict[str, tuple[Path, Path | None]] = {}
    for item in raw_maps:
        if "=" not in item:
            sys.exit(f"Invalid --map (expected speaker=path): {item!r}")
        key, ref = item.split("=", 1)
        key = key.strip()
        if not key:
            sys.exit(f"Invalid --map speaker key: {item!r}")
        out[key] = parse_ref_arg(ref)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Multivoice story PoC (writes only --out).")
    ap.add_argument("--story", required=True, help="Catalog story id (e.g. eunhye-gapeun-kkachi)")
    ap.add_argument(
        "--narrator",
        required=True,
        help="Narrator reference: path/to.wav or wav,txt",
    )
    ap.add_argument(
        "--default-character",
        required=True,
        help="Fallback character voice when --map omits a speaker",
    )
    ap.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="SPEAKER=REF",
        help="Optional per-speaker reference (repeatable)",
    )
    ap.add_argument("--out", type=Path, required=True, help="Output .m4a path (only destination written)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--no-dialogue-style", action="store_true")
    args = ap.parse_args()

    out = args.out.resolve()
    if str(out).startswith(str((ROOT / "data" / "audio").resolve())):
        sys.exit("--out must not be under data/audio")
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        story_text = story_markup_body_from_id(args.story.strip())
    except KeyError:
        sys.exit(f"Unknown story id: {args.story}")

    nar_wav, nar_txt = parse_ref_arg(args.narrator)
    char_wav, char_txt = parse_ref_arg(args.default_character)
    narrator_ref = load_voice_reference(nar_wav, nar_txt)
    default_char_ref = load_voice_reference(char_wav, char_txt)

    speaker_map: dict[str, object] = {}
    for key, (wav, txt) in _parse_map_items(args.map).items():
        speaker_map[key] = load_voice_reference(wav, txt)

    cache_voice_references(narrator_ref, default_char_ref, *speaker_map.values())
    resolve = build_voice_resolver(narrator_ref, default_char_ref, speaker_map)

    from audio_quality_config import dialogue_style_enabled

    dialogue_style = dialogue_style_enabled() and not args.no_dialogue_style

    gen = StoryGenerator(
        model_id=args.model,
        ref_audio=nar_wav,
        ref_text=load_ref_text(nar_txt or nar_wav.with_suffix(".txt")),
        max_chars=args.max_chars,
        temperature=args.temperature,
        dialogue_style=dialogue_style,
        verify_asr=False,
    )

    def resolve_chunk(chunk) -> object:
        return resolve(chunk)

    # StoryGenerator holds the loaded model; multivoice path uses per-chunk refs.
    narrate_story_multivoice(
        story_text,
        out,
        resolve_chunk,
        gen.model,
        max_chars=args.max_chars,
        temperature=args.temperature,
        dialogue_style=dialogue_style,
    )
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
