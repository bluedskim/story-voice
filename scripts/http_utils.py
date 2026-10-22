"""HTTP helpers for serve.py."""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any

_BOUNDARY_RE = re.compile(r'boundary=(?:"([^"]+)"|([^\s;]+))', re.I)


def client_ip(handler: BaseHTTPRequestHandler) -> str:
    cf = handler.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    forwarded = handler.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0]


def send_json(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    payload: Any,
    *,
    set_cookies: list[str] | None = None,
    clear_cookies: list[str] | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    if set_cookies:
        for cookie in set_cookies:
            handler.send_header("Set-Cookie", cookie)
    if clear_cookies:
        for name in clear_cookies:
            handler.send_header("Set-Cookie", f"{name}=; Max-Age=0; Path=/; HttpOnly")
    handler.end_headers()
    handler.wfile.write(body)


def cookie_secure_flag(handler: BaseHTTPRequestHandler) -> str:
    host = (handler.headers.get("Host") or "").split(":")[0].lower()
    if host in {"127.0.0.1", "localhost"}:
        return ""
    return "; Secure"


def make_session_cookie(token: str, handler: BaseHTTPRequestHandler) -> str:
    secure = cookie_secure_flag(handler)
    return (
        f"sv_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={30 * 24 * 3600}{secure}"
    )


def make_csrf_cookie(token: str, handler: BaseHTTPRequestHandler) -> str:
    secure = cookie_secure_flag(handler)
    return f"sv_csrf={token}; Path=/; SameSite=Lax; Max-Age={86400}{secure}"


def read_json_body(handler: BaseHTTPRequestHandler, max_bytes: int = 64_000) -> dict | None:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > max_bytes:
        return None
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def _parse_content_disposition(header: str) -> tuple[str | None, str | None]:
    name = None
    filename = None
    for piece in header.split(";"):
        piece = piece.strip()
        if piece.startswith("name="):
            name = piece[5:].strip().strip('"')
        elif piece.startswith("filename="):
            filename = piece[9:].strip().strip('"')
    return name, filename


def parse_multipart_body(body: bytes, content_type: str) -> dict | None:
    match = _BOUNDARY_RE.search(content_type)
    if not match:
        return None
    boundary = match.group(1) or match.group(2)
    delimiter = b"--" + boundary.encode("utf-8", "surrogateescape")
    result: dict = {}
    for chunk in body.split(delimiter):
        if not chunk or chunk == b"--" or chunk == b"--\r\n":
            continue
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if not chunk.strip():
            continue
        header_end = chunk.find(b"\r\n\r\n")
        if header_end < 0:
            continue
        headers = chunk[:header_end].decode("utf-8", errors="replace")
        content = chunk[header_end + 4 :]
        if content.endswith(b"\r\n"):
            content = content[:-2]
        name = None
        filename = None
        for line in headers.split("\r\n"):
            if line.lower().startswith("content-disposition:"):
                name, filename = _parse_content_disposition(line.split(":", 1)[1])
        if not name:
            continue
        if name == "transcript":
            result["transcript"] = content.decode("utf-8", errors="replace")
        elif name == "audio":
            result["audio_filename"] = filename or "upload.bin"
            result["audio_data"] = content
    if "audio_data" not in result:
        return None
    return result


def parse_multipart(handler: BaseHTTPRequestHandler, max_bytes: int) -> dict | None:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        return None
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > max_bytes:
        return None
    body = handler.rfile.read(length)
    return parse_multipart_body(body, content_type)
