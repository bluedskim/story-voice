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
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from download_filenames import (
    ascii_fallback_filename,
    content_disposition_attachment,
    download_basename,
)
from audio_quality_config import parse_asr_verify_body
from generation_service import EnqueueResult, GenerationService, JobState, StoryNotFoundError
from auth_csrf import CSRF_COOKIE, CSRF_HEADER, new_csrf_token, parse_cookies, validate_csrf
from auth_db import AuthDatabase
from auth_config import ensure_session_secret
from auth_email import is_log_mail_mode
from static_assets import app_js_served_body, inject_asset_versions, web_asset_versions
from auth_service import (
    AuthError,
    login,
    logout,
    nickname_available,
    send_verification,
    signup,
    user_from_session,
    user_is_admin,
    user_public,
    warn_if_no_admin_emails,
)
from http_utils import (
    client_ip,
    cookie_secure_flag,
    make_csrf_cookie,
    make_session_cookie,
    parse_multipart,
    read_json_body,
    send_json,
)
from rate_limit import RateLimiter
from story_catalog import build_manifest, build_public_catalog, write_manifest
from default_narration import default_story_audio, resolve_story_audio_path
from user_storage import (
    has_user_reference,
    migrate_legacy_voice_for_admin,
    user_ref_wav,
    user_reference_version,
)
from voice_service import (
    MAX_UPLOAD_BYTES,
    MIN_DURATION_SEC,
    MAX_DURATION_SEC,
    VoiceSaveError,
    confirm_voice_upload,
    default_record_script,
    has_reference,
    prepare_voice_upload,
)

WEB_DIR = ROOT / "web"
AUDIO_DIR = ROOT / "data" / "audio"
MANIFEST_PATH = WEB_DIR / "catalog.json"

STATIC_FILES = {
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/auth.js": ("auth.js", "application/javascript; charset=utf-8"),
    "/catalog.json": ("catalog.json", "application/json; charset=utf-8"),
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/icons/favicon.svg": ("icons/favicon.svg", "image/svg+xml"),
    "/icons/icon-16.png": ("icons/icon-16.png", "image/png"),
    "/icons/icon-32.png": ("icons/icon-32.png", "image/png"),
    "/icons/icon-48.png": ("icons/icon-48.png", "image/png"),
    "/icons/icon-180.png": ("icons/icon-180.png", "image/png"),
    "/icons/icon-192.png": ("icons/icon-192.png", "image/png"),
    "/icons/icon-512.png": ("icons/icon-512.png", "image/png"),
}

INJECTED_HTML_ROUTES = {"/", "/index.html"}
INJECTED_TEXT_ROUTES = {"/manifest.webmanifest"}
ASSET_VERSIONS = web_asset_versions()

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


def story_titles_map() -> dict[str, str]:
    from story_catalog import list_stories

    return {s.id: s.title for s in list_stories()}


class AppState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.auth_db = AuthDatabase()

        def refresh_catalog(_user_id: int | None = None) -> None:
            write_manifest(MANIFEST_PATH)

        refresh_catalog()
        self.generation = GenerationService(on_catalog_refresh=refresh_catalog)
        try:
            self.generation.enqueue_missing_default_stories()
        except RuntimeError:
            pass


class StoryVoiceHandler(BaseHTTPRequestHandler):
    server_version = "story-voice/3.0"

    @property
    def app(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    def _session_token(self) -> str | None:
        return parse_cookies(self).get("sv_session")

    def _current_user(self):
        return user_from_session(self.app.auth_db, self._session_token())

    def _ensure_csrf(self) -> bool:
        if not validate_csrf(self):
            send_json(
                self,
                HTTPStatus.FORBIDDEN,
                {"error": "요청을 확인할 수 없어요. 페이지를 새로고침해 주세요.", "code": "csrf_failed"},
            )
            return False
        return True

    def _require_logged_in(self):
        user = self._current_user()
        if not user:
            send_json(
                self,
                HTTPStatus.UNAUTHORIZED,
                {"error": "로그인이 필요해요.", "code": "auth_required"},
            )
            return None
        return user

    def _require_personal_voice(self, user):
        if has_user_reference(user.id):
            return True
        send_json(
            self,
            HTTPStatus.BAD_REQUEST,
            {
                "error": "먼저 목소리 탭에서 내 목소리를 저장해 주세요. 지금은 기본 낭독만 들을 수 있어요.",
                "code": "need_personal_voice",
            },
        )
        return False

    def _csrf_token_for_config(self) -> str:
        cookies = parse_cookies(self)
        token = cookies.get(CSRF_COOKIE)
        if not token:
            token = new_csrf_token()
        return token

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route != "/" and route.endswith("/"):
            route = route.rstrip("/")

        if route == "/api/config":
            csrf = self._csrf_token_for_config()
            user = self._current_user()
            send_json(
                self,
                HTTPStatus.OK,
                {
                    "recordScript": default_record_script(),
                    "csrfToken": csrf,
                    "authEmailDevMode": is_log_mail_mode(),
                    "assetVersions": ASSET_VERSIONS,
                    "limits": {
                        "minDurationSec": MIN_DURATION_SEC,
                        "maxDurationSec": MAX_DURATION_SEC,
                        "maxUploadBytes": MAX_UPLOAD_BYTES,
                    },
                    "user": user_public(user) if user else None,
                    "hasPersonalVoice": has_user_reference(user.id) if user else False,
                    "voiceReferenceVersion": (
                        user_reference_version(user.id)
                        if user and has_user_reference(user.id)
                        else None
                    ),
                },
                set_cookies=[make_csrf_cookie(csrf, self)],
            )
            return

        if route == "/api/auth/me":
            user = self._current_user()
            if not user:
                send_json(self, HTTPStatus.OK, {"user": None})
                return
            send_json(self, HTTPStatus.OK, {"user": user_public(user)})
            return

        if route == "/api/users/nickname-available":
            query = parse_qs(parsed.query)
            nickname = (query.get("nickname") or [""])[0].strip()
            try:
                available = nickname_available(self.app.auth_db, nickname) if nickname else False
            except AuthError as exc:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "available": False})
                return
            send_json(self, HTTPStatus.OK, {"available": available})
            return

        if route == "/api/catalog":
            user = self._current_user()
            if not user:
                send_json(self, HTTPStatus.OK, build_public_catalog())
                return
            send_json(self, HTTPStatus.OK, build_manifest(user_id=user.id))
            return

        if route == "/api/voice/reference.wav":
            user = self._current_user()
            if not user:
                self._send_error(HTTPStatus.UNAUTHORIZED)
                return
            if user_is_admin(user):
                migrate_legacy_voice_for_admin(user.id)
            if not has_user_reference(user.id):
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            file_path = _safe_resolve(user_ref_wav(user.id).parent, user_ref_wav(user.id).name)
            if file_path is None or not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(file_path, "audio/wav")
            return

        if route == "/api/voice":
            user = self._current_user()
            if not user:
                send_json(self, HTTPStatus.OK, {"hasReference": False, "requiresLogin": True})
                return
            if user_is_admin(user):
                migrate_legacy_voice_for_admin(user.id)
            payload = {"hasReference": has_reference(user.id)}
            if has_user_reference(user.id):
                payload["referenceVersion"] = user_reference_version(user.id)
            send_json(self, HTTPStatus.OK, payload)
            return

        if route == "/api/generation/status":
            user = self._current_user()
            uid = user.id if user else None
            send_json(self, HTTPStatus.OK, self.app.generation.status_snapshot(uid))
            return

        base_route = route.split("?", 1)[0]
        if base_route in INJECTED_HTML_ROUTES:
            file_path = _safe_resolve(WEB_DIR, "index.html")
            if file_path is None or not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            versions = web_asset_versions()
            body = inject_asset_versions(file_path.read_text(encoding="utf-8"), versions).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if base_route in INJECTED_TEXT_ROUTES:
            file_path = _safe_resolve(WEB_DIR, "manifest.webmanifest")
            if file_path is None or not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND)
                return
            versions = web_asset_versions()
            body = inject_asset_versions(file_path.read_text(encoding="utf-8"), versions).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if base_route in STATIC_FILES:
            filename, content_type = STATIC_FILES[base_route]
            if not self._send_static_web_file(filename, content_type):
                self._send_error(HTTPStatus.NOT_FOUND)
            return

        if (
            base_route.startswith("/styles.css")
            or base_route.startswith("/app.js")
            or base_route.startswith("/auth.js")
        ):
            base = base_route.split("?", 1)[0].lstrip("/")
            if base in {"styles.css", "app.js", "auth.js"}:
                ctype = (
                    "text/css; charset=utf-8"
                    if base.endswith(".css")
                    else "application/javascript; charset=utf-8"
                )
                if not self._send_static_web_file(base, ctype):
                    self._send_error(HTTPStatus.NOT_FOUND)
                return

        if route.startswith("/audio/"):
            query = parse_qs(parsed.query)
            download = query.get("download", [""])[0].lower() in {"1", "true", "yes"}
            self._serve_audio(route, as_download=download)
            return

        self._send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        ip = client_ip(self)

        if route == "/api/users/signup/send-verification":
            if not self._ensure_csrf():
                return
            body = read_json_body(self)
            if body is None:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 요청이에요."})
                return
            login_id = (body.get("loginId") or body.get("email") or "").strip()
            try:
                send_verification(self.app.auth_db, login_id, ip)
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            except AuthError as exc:
                payload = {"error": str(exc), "code": exc.code}
                if exc.retry_after_sec is not None:
                    payload["retryAfterSec"] = exc.retry_after_sec
                send_json(self, HTTPStatus(exc.status), payload)
            return

        if route == "/api/users/signup":
            if not self._ensure_csrf():
                return
            body = read_json_body(self)
            if body is None:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 요청이에요."})
                return
            try:
                user = signup(
                    self.app.auth_db,
                    (body.get("loginId") or body.get("email") or "").strip(),
                    (body.get("nickname") or "").strip(),
                    body.get("password") or "",
                    (body.get("verificationCode") or "").strip(),
                    ip,
                    after_create=lambda _u: self._schedule_default_narrations(),
                )
                send_json(self, HTTPStatus.CREATED, {"user": user_public(user)})
            except AuthError as exc:
                send_json(self, HTTPStatus(exc.status), {"error": str(exc), "code": exc.code})
            return

        if route == "/api/auth/login":
            if not self._ensure_csrf():
                return
            body = read_json_body(self)
            if body is None:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 요청이에요."})
                return
            try:
                token, user = login(
                    self.app.auth_db,
                    (body.get("loginId") or body.get("email") or "").strip(),
                    body.get("password") or "",
                )
                csrf = self._csrf_token_for_config()
                send_json(
                    self,
                    HTTPStatus.OK,
                    {"accessToken": token, "user": user_public(user)},
                    set_cookies=[
                        make_session_cookie(token, self),
                        make_csrf_cookie(csrf, self),
                    ],
                )
            except AuthError as exc:
                send_json(self, HTTPStatus(exc.status), {"error": str(exc), "code": exc.code})
            return

        if route == "/api/auth/logout":
            if not self._ensure_csrf():
                return
            logout(self.app.auth_db, self._session_token())
            secure = cookie_secure_flag(self)
            send_json(
                self,
                HTTPStatus.OK,
                {"ok": True},
                set_cookies=[
                    f"sv_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}",
                    f"sv_csrf=; Path=/; SameSite=Lax; Max-Age=0{secure}",
                ],
            )
            return

        if route == "/api/voice/prepare":
            if not voice_rate.allow(ip):
                send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "요청이 너무 많아요. 잠시 후 다시 시도해 주세요."})
                return
            if not self._ensure_csrf():
                return
            user = self._require_logged_in()
            if user is None:
                return
            self._handle_voice_prepare(user)
            return

        if route == "/api/voice/confirm":
            if not voice_rate.allow(ip):
                send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "요청이 너무 많어요. 잠시 후 다시 시도해 주세요."})
                return
            if not self._ensure_csrf():
                return
            user = self._require_logged_in()
            if user is None:
                return
            self._handle_voice_confirm(user)
            return

        if route == "/api/voice":
            send_json(
                self,
                HTTPStatus.GONE,
                {"error": "목소리 저장은 ‘받아쓰기 확인’ 후 ‘이 목소리로 저장’을 사용해 주세요.", "code": "use_prepare_confirm"},
            )
            return

        if route.startswith("/api/generation/story/"):
            story_id = route[len("/api/generation/story/") :]
            if not STORY_ID_RE.match(story_id):
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 이야기 id"})
                return
            if not gen_rate.allow(ip):
                send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "요청이 너무 많아요."})
                return
            if not self._ensure_csrf():
                return
            user = self._require_logged_in()
            if user is None:
                return
            if not self._require_personal_voice(user):
                return
            body = read_json_body(self)
            if body is None:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 요청이에요."})
                return
            try:
                asr_flag = parse_asr_verify_body(body)
            except ValueError:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "asrVerify는 true 또는 false여야 해요."})
                return
            try:
                result = self.app.generation.enqueue_story(
                    story_id,
                    user.id,
                    is_admin=user_is_admin(user),
                    asr_verify_request=asr_flag,
                )
                self._send_enqueue_result(result)
            except StoryNotFoundError:
                send_json(self, HTTPStatus.NOT_FOUND, {"error": "이야기를 찾을 수 없어요."})
            except RuntimeError as exc:
                send_json(self, HTTPStatus.CONFLICT, {"error": str(exc)})
            return

        if route == "/api/generation/all":
            if not gen_rate.allow(ip):
                send_json(self, HTTPStatus.TOO_MANY_REQUESTS, {"error": "요청이 너무 많아요."})
                return
            if not self._ensure_csrf():
                return
            user = self._require_logged_in()
            if user is None:
                return
            if not self._require_personal_voice(user):
                return
            body = read_json_body(self)
            if body is None:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 요청이에요."})
                return
            try:
                asr_flag = parse_asr_verify_body(body)
            except ValueError:
                send_json(self, HTTPStatus.BAD_REQUEST, {"error": "asrVerify는 true 또는 false여야 해요."})
                return
            try:
                result = self.app.generation.enqueue_all(
                    user.id,
                    is_admin=user_is_admin(user),
                    asr_verify_request=asr_flag,
                )
                self._send_enqueue_result(result)
            except RuntimeError as exc:
                send_json(self, HTTPStatus.CONFLICT, {"error": str(exc)})
            return

        self._send_error(HTTPStatus.NOT_FOUND)

    def _handle_voice_prepare(self, user) -> None:
        if self.app.generation.is_generating():
            send_json(
                self,
                HTTPStatus.CONFLICT,
                {
                    "error": "이야기를 만드는 중이에요. 잠시 후 다시 시도해 주세요.",
                    "code": "generation_busy",
                },
            )
            return
        form = parse_multipart(self, MAX_UPLOAD_BYTES + 4096)
        if form is None or "audio_data" not in form:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "오디오 파일이 필요해요."})
            return
        audio_data = form["audio_data"]
        if len(audio_data) > MAX_UPLOAD_BYTES:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "파일이 너무 커요."})
            return
        suffix = Path(form.get("audio_filename") or "upload.bin").suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=ROOT / "out") as tmp:
            tmp.write(audio_data)
            tmp_path = Path(tmp.name)
        try:
            result = prepare_voice_upload(user.id, tmp_path, len(audio_data))
            send_json(self, HTTPStatus.OK, result)
        except VoiceSaveError as exc:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": exc.code})
        finally:
            tmp_path.unlink(missing_ok=True)

    def _handle_voice_confirm(self, user) -> None:
        body = read_json_body(self, max_bytes=256_000)
        if body is None:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "잘못된 요청이에요."})
            return
        token = (body.get("pendingToken") or "").strip()
        transcript = body.get("transcript") or ""
        if not token:
            send_json(self, HTTPStatus.BAD_REQUEST, {"error": "확인 코드가 없어요."})
            return
        try:
            result = confirm_voice_upload(user.id, token, transcript)
            if has_user_reference(user.id):
                result["referenceVersion"] = user_reference_version(user.id)
            send_json(self, HTTPStatus.OK, result)
        except VoiceSaveError as exc:
            status = HTTPStatus.BAD_REQUEST
            if exc.code in {"expired_token", "invalid_token"}:
                status = HTTPStatus.GONE
            send_json(self, status, {"error": str(exc), "code": exc.code})

    def _schedule_default_narrations(self) -> None:
        try:
            self.app.generation.enqueue_missing_default_stories()
        except RuntimeError:
            pass

    def _send_enqueue_result(self, result: EnqueueResult) -> None:
        job = result.job
        payload = {"job": job.to_public(), "deduplicated": not result.created}
        if result.created:
            send_json(self, HTTPStatus.ACCEPTED, payload)
            return
        if job.state in {JobState.QUEUED, JobState.RUNNING}:
            send_json(self, HTTPStatus.ACCEPTED, payload)
        else:
            send_json(self, HTTPStatus.OK, payload)

    def _serve_audio(self, route: str, as_download: bool = False) -> None:
        user = self._current_user()
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
        titles = story_titles_map()
        if story_id not in titles:
            self._send_error(HTTPStatus.NOT_FOUND)
            return
        if user:
            resolved = resolve_story_audio_path(user.id, story_id)
        else:
            guest_default = default_story_audio(story_id)
            resolved = guest_default if guest_default.is_file() else None
        if resolved is None:
            self._send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = _safe_resolve(resolved.parent, resolved.name)
        if file_path is None or not file_path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND)
            return
        disposition = None
        if as_download:
            title = titles.get(story_id, story_id)
            utf8_name = download_basename(title)
            ascii_name = ascii_fallback_filename(story_id)
            disposition = content_disposition_attachment(utf8_name, ascii_name)
        self._send_file(file_path, "audio/mp4", content_disposition=disposition)

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

    def _send_static_web_file(self, filename: str, content_type: str) -> bool:
        file_path = _safe_resolve(WEB_DIR, filename)
        if file_path is None or not file_path.is_file():
            return False
        if filename == "app.js":
            body = app_js_served_body()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return True
        self._send_file(file_path, content_type)
        return True

    def _send_file(self, file_path: Path, content_type: str, content_disposition: str | None = None) -> None:
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
        if content_disposition:
            self.send_header("Content-Disposition", content_disposition)
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

    ensure_session_secret()
    warn_if_no_admin_emails()

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "out").mkdir(parents=True, exist_ok=True)

    app_state = AppState()
    server = ThreadingHTTPServer((args.host, args.port), StoryVoiceHandler)
    server.app_state = app_state

    url = f"http://localhost:{args.port}/"
    print(f"story-voice at {url}", file=sys.stderr)
    gen = os.environ.get("STORY_VOICE_GENERATOR", "mlx")
    print(f"Generator: {gen}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
