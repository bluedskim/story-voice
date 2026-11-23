#!/usr/bin/env python3
"""Node tests for web/playback.js (buffered story playback start)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test_playback_client.mjs"


def main() -> int:
    proc = subprocess.run(["node", str(SCRIPT)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout)
        return 1
    print("OK: playback client tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())