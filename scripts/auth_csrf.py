"""CSRF double-submit + same-origin checks."""

from __future__ import annotations

import secrets
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

CSRF_COOKIE = "sv_csrf"
CSRF_HEADER = "X-CSRF-Token"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def parse_cookies(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    raw = handler.headers.get("Cookie", "")
    out: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _origin_allowed(handler: BaseHTTPRequestHandler) -> bool:
    host = (handler.headers.get("Host") or "").split(":")[0].lower()
    if not host:
        return False
    origin = handler.headers.get("Origin")
    if origin:
        try:
            o = urlparse(origin)
            return o.hostname and o.hostname.lower() == host
        except ValueError:
            return False
    referer = handler.headers.get("Referer")
    if referer:
        try:
            r = urlparse(referer)
            return r.hostname and r.hostname.lower() == host
        except ValueError:
            return False
    # Same-origin fetch from address bar forms may omit both; allow loopback only.
    return host in {"127.0.0.1", "localhost"}


def validate_csrf(handler: BaseHTTPRequestHandler) -> bool:
    if not _origin_allowed(handler):
        return False
    cookies = parse_cookies(handler)
    cookie_token = cookies.get(CSRF_COOKIE, "")
    header_token = handler.headers.get(CSRF_HEADER, "")
    if not cookie_token or not header_token:
        return False
    return secrets.compare_digest(cookie_token, header_token)
