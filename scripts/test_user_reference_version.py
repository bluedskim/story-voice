#!/usr/bin/env python3
"""user_reference_version helper."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from user_storage import user_ref_wav, user_reference_version  # noqa: E402


def test_user_reference_version() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        wav = user_ref_wav(42)
        wav.parent.mkdir(parents=True, exist_ok=True)
        assert user_reference_version(42) is None
        wav.write_bytes(b"RIFF" + b"\0" * 40)
        v1 = user_reference_version(42)
        assert v1 is not None
        wav.write_bytes(b"RIFF" + b"\1" * 40)
        v2 = user_reference_version(42)
        assert v2 is not None and v2 >= v1


def main() -> None:
    test_user_reference_version()
    print("OK: user_reference_version tests")


if __name__ == "__main__":
    main()
