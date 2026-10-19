#!/usr/bin/env python3
"""Minimal web player: whitelisted static files + catalog audio with Range support."""

from __future__ import annotations

import argparse
import json
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from story_catalog import write_manifest

WEB_DIR = ROOT / "web"
AUDIO_DIR = ROOT / "data" / "audio"
MANIFEST_PATH = WEB_DIR / "catalog.json"

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/catalog.json": ("catalog.json", "application/json; charset=utf-8"),
}

STORY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _safe_resolve(base: Path, name: str) -> Path | None:
    """Resolve base/name; return None if path escapes base."""
    try:
        candidate = (base / name).resolve()
        base_resolved = base.resolve()
        candidate.relative_to(base_resolved)
        return candidate
    except (OSError, ValueError):
        return None


def load_allowed_audio_ids() -> set[str]:
    if not MANIFEST_PATH.is_file():
        return set()
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    allowed: set[str] = set()
    for story in data.get("stories", []):
        story_id = story.get("id")
        if not story_id or not STORY_ID_RE.match(story_id):
            continue
        if story.get("hasAudio"):
            allowed.add(story_id)
    return allowed


class StoryVoiceHandler(BaseHTTPRequestHandler):
    server_version = "story-voice/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route != "/" and route.endswith("/"):
            route = route.rstrip("/")

        if route in STATIC_FILES:
            filename, content_type = STATIC_FILES[route]
            file_path = _safe_resolve(WEB_DIR, filename)
            if file_path is None or not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(file_path, content_type)
            return

        if route.startswith("/audio/"):
            name = route[len("/audio/") :]
            if "/" in name or name != Path(name).name:
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            if not name.endswith(".m4a"):
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            story_id = name[: -len(".m4a")]
            if not STORY_ID_RE.match(story_id):
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            allowed = getattr(self.server, "allowed_audio_ids", set())
            if story_id not in allowed:
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            file_path = _safe_resolve(AUDIO_DIR, name)
            if file_path is None or not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(file_path, "audio/mp4")
            return

        self._send_error(HTTPStatus.NOT_FOUND)

    def _send_error(self, code: HTTPStatus) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _parse_range(self, file_size: int) -> tuple[int, int] | None:
        header = self.headers.get("Range")
        if not header:
            return None
        if not header.startswith("bytes="):
            return "invalid"
        spec = header[6:].strip()
        if "," in spec:
            return "invalid"
        if spec.startswith("-"):
            try:
                suffix = int(spec[1:])
            except ValueError:
                return "invalid"
            if suffix <= 0:
                return "invalid"
            start = max(0, file_size - suffix)
            end = file_size - 1
            return (start, end)
        parts = spec.split("-", 1)
        try:
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except ValueError:
            return "invalid"
        if start > end or start >= file_size:
            return "invalid"
        end = min(end, file_size - 1)
        return (start, end)

    def _send_file(self, file_path: Path, content_type: str) -> None:
        file_size = file_path.stat().st_size
        parsed_range = self._parse_range(file_size)

        if parsed_range == "invalid":
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return

        if parsed_range is None:
            start, end = 0, file_size - 1
            status = HTTPStatus.OK
        else:
            start, end = parsed_range
            status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        with file_path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the story-voice web player.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (127.0.0.1 for tunnel/LAN via reverse proxy; 0.0.0.0 to expose port)",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    write_manifest(MANIFEST_PATH)

    allowed_audio = load_allowed_audio_ids()
    server = ThreadingHTTPServer((args.host, args.port), StoryVoiceHandler)
    server.allowed_audio_ids = allowed_audio

    url = f"http://{args.host}:{args.port}/"
    if args.host in {"127.0.0.1", "localhost"}:
        url = f"http://localhost:{args.port}/"
    print(f"story-voice player at {url}", file=sys.stderr)
    print(f"Audio files allowed: {len(allowed_audio)}", file=sys.stderr)
    if args.host == "0.0.0.0":
        print("LAN: http://<host-ip>:8765/ (or use a tunnel to localhost)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
