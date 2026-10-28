#!/usr/bin/env python3
"""Anonymous catalog and audio access for shared default narrations."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from default_narration import default_story_audio
from story_catalog import build_public_catalog, list_stories


def test_public_catalog_includes_default_audio(tmp_path: Path | None = None) -> None:
    stories = list_stories()
    assert stories, "expected story fixtures"
    story_id = stories[0].id
    audio_dir = ROOT / "data" / "audio" / "default"
    audio_dir.mkdir(parents=True, exist_ok=True)
    sample = audio_dir / f"{story_id}.m4a"
    created = False
    if not sample.is_file():
        sample.write_bytes(b"\x00" * 64)
        created = True
    try:
        cat = build_public_catalog()
        row = next(s for s in cat["stories"] if s["id"] == story_id)
        assert row["hasAudio"] is True
        assert row["audioSource"] == "default"
        assert row["hasPersonalAudio"] is False
        assert row["audioUrl"] == f"/audio/{story_id}.m4a"
        assert "requiresLoginForAudio" not in cat
    finally:
        if created:
            sample.unlink(missing_ok=True)


def main() -> int:
    test_public_catalog_includes_default_audio()
    print("OK: guest default catalog tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
