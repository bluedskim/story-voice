"""Every ES module imported by web/*.js must be served (else the app fails to load)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import serve  # noqa: E402
from static_assets import CACHE_BUST_ASSETS  # noqa: E402

IMPORT_RE = re.compile(r'from\s+"\./([\w.-]+\.js)"')


def imported_modules() -> set[str]:
    mods: set[str] = set()
    for js in (ROOT / "web").glob("*.js"):
        mods.update(IMPORT_RE.findall(js.read_text(encoding="utf-8")))
    return mods


def test_imported_modules_are_routed_and_versioned() -> None:
    mods = imported_modules()
    assert "playback.js" in mods
    for mod in mods:
        assert f"/{mod}" in serve.STATIC_FILES, mod
        assert mod in CACHE_BUST_ASSETS, mod


if __name__ == "__main__":
    test_imported_modules_are_routed_and_versioned()
    print("ok")
