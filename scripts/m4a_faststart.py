#!/usr/bin/env python3
"""Check / losslessly remux story m4a files so the ``moov`` atom sits before ``mdat``.

With ``moov`` at the end the browser must fetch the file tail (extra Range
round-trip) before it can decode anything, which makes slow starts worse.

Usage:
    .venv/bin/python scripts/m4a_faststart.py data/audio/default            # report only
    .venv/bin/python scripts/m4a_faststart.py data/audio/default --apply    # remux in place

Remux uses ``ffmpeg -c copy -movflags +faststart`` (no re-encode; audio samples
unchanged). Each file is written to a temp file next to it and atomically
replaced only after the result is verified.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path


def top_level_atoms(path: Path) -> list[str]:
    atoms: list[str] = []
    size_total = path.stat().st_size
    with path.open("rb") as fh:
        pos = 0
        while pos + 8 <= size_total:
            fh.seek(pos)
            header = fh.read(8)
            if len(header) < 8:
                break
            size, kind = struct.unpack(">I4s", header)
            if size == 1:
                size = struct.unpack(">Q", fh.read(8))[0]
            elif size == 0:
                size = size_total - pos
            if size < 8:
                break
            atoms.append(kind.decode("latin-1"))
            pos += size
    return atoms


def is_faststart(path: Path) -> bool:
    atoms = top_level_atoms(path)
    if "moov" not in atoms or "mdat" not in atoms:
        return False
    return atoms.index("moov") < atoms.index("mdat")


def remux_faststart(path: Path) -> None:
    tmp = path.with_name(f".{path.stem}.faststart.tmp.m4a")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                "-map", "0", "-c", "copy", "-movflags", "+faststart", str(tmp),
            ],
            check=True,
        )
        if not is_faststart(tmp):
            raise RuntimeError(f"remux did not move moov to front: {path}")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def iter_m4a(paths: list[Path]):
    for p in paths:
        if p.is_dir():
            yield from sorted(x for x in p.rglob("*.m4a") if not x.name.startswith("."))
        elif p.suffix.lower() == ".m4a":
            yield p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--apply", action="store_true", help="remux files that are not faststart")
    args = ap.parse_args(argv)
    pending = 0
    for f in iter_m4a(args.paths):
        if is_faststart(f):
            print(f"ok        {f}")
            continue
        pending += 1
        if args.apply:
            remux_faststart(f)
            print(f"remuxed   {f}")
        else:
            print(f"moov-end  {f}")
    if pending and not args.apply:
        print(f"{pending} file(s) need faststart; rerun with --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
