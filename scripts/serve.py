#!/usr/bin/env python3
"""Web player + voice setup + background story generation."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generation_service import GenerationService
from http_utils import client_ip, parse_multipart, read_json_body, send_json
from rate_limit import RateLimiter
from story_catalog import write_manifest
from voice_service import (
    MAX_UPLOAD_BYTES,
    MIN_DURATION_SEC,
    MAX_DURATION_SEC,
    VoiceSaveError,
    default_record_script,
    has_reference,
    save_reference,
)

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

voice_rate = RateLimiter(max_events=6, window_sec=60.0)
gen_rate = RateLimiter(max_events=10, window_sec=60.0)


def _safe_resolve(base: Path, name: str) -> Path | None:
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


class AppState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.allowed_audio_ids: set[str] = set()

        def refresh() -> None:
            write_manifest(MANIFEST_PATH)
            with self.lock:
                self.allowed_audio_ids = load_allowed_audio_ids()

        refresh()
        self.generation = GenerationService(on_catalog_refresh=refresh)


class StoryVoiceHandler(BaseHTTPRequestHandler):
    server_version = "story-voice/2.0"

    @property
    def app(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route != "/" and route.endswith("/"):
            route = route.rstrip("/")

        if route == "/api/config":
            send_json(
                self,
                HTTPStatus.OK,
                {
                    "recordScript": default_record_script(),
                    "limits": {
                        "minDurationSec": MIN_DURATION_SEC,
                        "maxDurationSec": MAX_DURATION_SEC,
                        "maxUploadBytes": MAX_UPLOAD_BYTES,
                    },
                },
            )
            return

        if route == "/api/voice":
            send_json(self, HTTPStatus.OK, {"hasReference": has_reference()})
            return

        if route == "/api/generation/status":
            send_json(self, HTTPStatus.OK, self.app.generation.status_snapshot())
            return

        if route in STATIC_FILES:
            filename, content_type = STATIC_FILES[route]
            file_path = _safe_resolve(WEB_DIR, filename)
            if file_path is None or not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(file_path, content_type)
            return

        if route.startswith("/audio/"):
            self._serve_audio(route)
            return

        self._send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        ip = client_ip(self)

        if route == "/api/voice":
            if not voice_rate.allow(ip):
                send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "요청이 너무 많아요. 잠시 후 다시 시도해 주세요."})
                return
            self._handle_voice_upload()
            return

        if route.startswith("/api/generation/story/"):
            story_id = route[len("/api/generation/story/") :]
            if not STORY_ID_RE.match(story_id):
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 이야기 id"})
                return
            if not gen_rate.allow(ip):
                send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "요청이 너무 많아요."})
                return
            try:
                job = self.app.generation.enqueue_story(story_id)
                send_json(self, HTTPStatus.ACCEPTED, {"job": job.to_public()})
            except RuntimeError as exc:
                send_json(self, HTTPStatus.CONFLICT, {"error": str(exc)})
            return

        if route == "/api/generation/all":
            if not gen_rate.allow(ip):
                send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "요청이 너무 많아요."})
                return
            try:
                job = self.app.generation.enqueue_all()
                send_json(self, HTTPStatus.ACCEPTED, {"job": job.to_public()})
            except RuntimeError as exc:
                send_json(self, HTTPStatus.CONFLICT, {"error": str(exc)})
            return

        self._send_error(HTTPStatus.NOT_FOUND)

    def _handle_voice_upload(self) -> None:
        form = parse_multipart(self, MAX_UPLOAD_BYTES + 4096)
        if form is None or "audio_data" not in form:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "오디오 파일이 필요해요."})
            return
        transcript = form.get("transcript") or ""
        audio_data = form["audio_data"]
        if len(audio_data) > MAX_UPLOAD_BYTES:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "파일이 너무 커요."})
            return
        suffix = Path(form.get("audio_filename") or "upload.bin").suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=ROOT / "out") as tmp:
            tmp.write(audio_data)
            tmp_path = Path(tmp.name)
        try:
            result = save_reference(tmp_path, transcript, len(audio_data))
            send_json(self, HTTPStatus.OK, result)
        except VoiceSaveError as exc:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": exc.code})
        finally:
            tmp_path.unlink(missing_ok=True)

    def _serve_audio(self, route: str) -> None:
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
        with self.app.lock:
            allowed = set(self.app.allowed_audio_ids)
        if story_id not in allowed:
            self._send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = _safe_resolve(AUDIO_DIR, name)
        if file_path is None or not file_path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_file(file_path, "audio/mp4")

    def _send_error(self, code: HTTPStatus) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _parse_range(self, file_size: int):
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
        help="Bind address (127.0.0.1 for tunnel; 0.0.0.0 for LAN)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--generator",
        choices=("mlx", "fake"),
        default=None,
        help="Override STORY_VOICE_GENERATOR env (fake for tests without MLX)",
    )
    args = parser.parse_args()

    if args.generator:
        os.environ["STORY_VOICE_GENERATOR"] = args.generator

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "out").mkdir(parents=True, exist_ok=True)

    app_state = AppState()
    server = ThreadingHTTPServer((args.host, args.port), StoryVoiceHandler)
    server.app_state = app_state

    url = f"http://localhost:{args.port}/"
    print(f"story-voice at {url}", file=sys.stderr)
    print(f"Audio ids: {len(app_state.allowed_audio_ids)}", file=sys.stderr)
    gen = os.environ.get("STORY_VOICE_GENERATOR", "mlx")
    print(f"Generator: {gen}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
