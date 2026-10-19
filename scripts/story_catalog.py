"""Parse story files and build the web catalog manifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORIES_DIR = ROOT / "content" / "stories"
AUDIO_DIR = ROOT / "data" / "audio"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    order: int
    path: Path
    body: str

    @property
    def audio_path(self) -> Path:
        return AUDIO_DIR / f"{self.id}.m4a"

    def has_audio(self) -> bool:
        return self.audio_path.is_file()


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    body = text[match.end() :].strip()
    return meta, body


def load_story(path: Path) -> Story:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    story_id = meta.get("id") or path.stem
    title = meta.get("title") or story_id
    order = int(meta.get("order", "999"))
    return Story(id=story_id, title=title, order=order, path=path, body=body)


def list_stories(stories_dir: Path | None = None) -> list[Story]:
    base = stories_dir or STORIES_DIR
    stories = [load_story(p) for p in sorted(base.glob("*.txt"))]
    return sorted(stories, key=lambda s: (s.order, s.title))


def build_manifest(stories_dir: Path | None = None, audio_dir: Path | None = None) -> dict:
    audio_base = audio_dir or AUDIO_DIR
    stories = list_stories(stories_dir)
    items = []
    for story in stories:
        audio_file = audio_base / f"{story.id}.m4a"
        entry = {
            "id": story.id,
            "title": story.title,
            "order": story.order,
            "text": story.body,
            "hasAudio": audio_file.is_file(),
        }
        if audio_file.is_file():
            entry["audioUrl"] = f"/audio/{story.id}.m4a"
        items.append(entry)
    return {"stories": items}


def write_manifest(
    out_path: Path,
    stories_dir: Path | None = None,
    audio_dir: Path | None = None,
) -> dict:
    manifest = build_manifest(stories_dir, audio_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build web/catalog.json from story files.")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "web" / "catalog.json",
        help="Output manifest path",
    )
    parser.add_argument("--stories-dir", type=Path, default=STORIES_DIR)
    parser.add_argument("--audio-dir", type=Path, default=AUDIO_DIR)
    args = parser.parse_args()
    manifest = write_manifest(args.out, args.stories_dir, args.audio_dir)
    ready = sum(1 for s in manifest["stories"] if s["hasAudio"])
    print(f"Wrote {args.out} ({ready}/{len(manifest['stories'])} with audio)")


if __name__ == "__main__":
    main()
