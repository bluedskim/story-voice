#!/usr/bin/env python3
"""Minimal local web player for bedtime stories (static + audio files)."""

from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from story_catalog import write_manifest

WEB_DIR = ROOT / "web"
AUDIO_DIR = ROOT / "data" / "audio"


class StoryVoiceHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        # Allow phone on home LAN to load audio from Mac mini.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the story-voice web player.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (0.0.0.0 for LAN)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    write_manifest(WEB_DIR / "catalog.json")

    handler = partial(StoryVoiceHandler, directory=str(WEB_DIR))

    # Symlink or serve audio: SimpleHTTPRequestHandler only serves one directory.
    # Mount audio under web/audio via manifest URLs — copy/symlink at startup.
    audio_link = WEB_DIR / "audio"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    if audio_link.is_symlink():
        if audio_link.resolve() != AUDIO_DIR.resolve():
            audio_link.unlink()
            audio_link.symlink_to(AUDIO_DIR, target_is_directory=True)
    elif not audio_link.exists():
        try:
            audio_link.symlink_to(AUDIO_DIR, target_is_directory=True)
        except OSError:
            audio_link.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://localhost:{args.port}/"
    print(f"story-voice player at {url}", file=sys.stderr)
    if args.host == "0.0.0.0":
        print("On your phone (same Wi‑Fi): http://<mac-mini-ip>:8765/", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
