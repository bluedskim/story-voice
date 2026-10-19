"""HTTP helpers for serve.py."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any


def client_ip(handler: BaseHTTPRequestHandler) -> str:
    cf = handler.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    forwarded = handler.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0]


def send_json(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


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


def parse_multipart(handler: BaseHTTPRequestHandler, max_bytes: int) -> dict | None:
    import cgi

    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        return None
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > max_bytes:
        return None
    fs = cgi.FieldStorage(
        fp=handler.rfile,
        headers=handler.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(length),
        },
    )
    result: dict = {}
    if "transcript" in fs:
        result["transcript"] = fs["transcript"].value
    if "audio" in fs:
        field = fs["audio"]
        result["audio_filename"] = field.filename
        result["audio_data"] = field.file.read()
    return result
