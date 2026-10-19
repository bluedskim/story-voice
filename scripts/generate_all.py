#!/usr/bin/env python3
"""Generate audio for all stories (model loaded once). Skips existing files unless --force."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clone_story import DEFAULT_AUDIO_DIR, StoryGenerator, generate_from_story_file
from story_catalog import list_stories, write_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate audio for every story in the catalog.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if .m4a exists")
    parser.add_argument("--model", default=None, help="Override mlx-community model id")
    parser.add_argument("--sentence-pause", type=float, default=None)
    parser.add_argument("--paragraph-pause", type=float, default=None)
    parser.add_argument("--pause", type=float, default=None, help="Set both pauses (validated --pause)")
    parser.add_argument("--max-chars", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    args = parser.parse_args()

    stories = list_stories()
    if not stories:
        sys.exit("No stories found in content/stories/")

    kwargs = {}
    if args.model:
        kwargs["model_id"] = args.model
    if args.sentence_pause is not None:
        kwargs["sentence_pause"] = args.sentence_pause
    if args.paragraph_pause is not None:
        kwargs["paragraph_pause"] = args.paragraph_pause
    if args.pause is not None:
        kwargs["sentence_pause"] = args.pause
        kwargs["paragraph_pause"] = args.pause
    if args.max_chars is not None:
        kwargs["max_chars"] = args.max_chars
    if args.temperature is not None:
        kwargs["temperature"] = args.temperature

    generator = StoryGenerator(**kwargs)

    for story in stories:
        out = DEFAULT_AUDIO_DIR / f"{story.id}.m4a"
        if out.is_file() and not args.force:
            print(f"Skip {story.id} (already exists)", file=sys.stderr)
            continue
        print(f"=== {story.title} ({story.id}) ===", file=sys.stderr)
        generate_from_story_file(story.path, output_m4a=out, generator=generator)

    manifest_path = ROOT / "web" / "catalog.json"
    write_manifest(manifest_path)
    print(f"Updated {manifest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
