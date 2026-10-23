"""Auth/mail/session configuration."""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION_SECRET_FILE = ROOT / "data" / ".session_secret"

_session_secret: bytes | None = None


def is_production() -> bool:
    raw = os.environ.get("STORY_VOICE_PRODUCTION", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def mail_from() -> str:
    return os.environ.get("STORY_VOICE_MAIL_FROM", "Story Voice <noreply@baem.app>").strip()


def mail_mode() -> str:
    mode = os.environ.get("STORY_VOICE_MAIL_MODE", "").strip().lower()
    if mode in {"resend", "log"}:
        return mode
    if os.environ.get("RESEND_API_KEY", "").strip():
        return "resend"
    return "log"


def resend_api_key() -> str:
    return os.environ.get("RESEND_API_KEY", "").strip()


def ensure_session_secret() -> bytes:
    global _session_secret
    if _session_secret is not None:
        return _session_secret
    env = os.environ.get("STORY_VOICE_SESSION_SECRET", "").strip()
    if env:
        _session_secret = env.encode("utf-8")
        return _session_secret
    if SESSION_SECRET_FILE.is_file():
        _session_secret = SESSION_SECRET_FILE.read_bytes().strip()
        return _session_secret
    if is_production():
        print(
            "STORY_VOICE_SESSION_SECRET is required in production (or set STORY_VOICE_PRODUCTION=0 for dev).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_urlsafe(48)
    SESSION_SECRET_FILE.write_text(generated + "\n", encoding="utf-8")
    _session_secret = generated.encode("utf-8")
    return _session_secret


def session_secret_bytes() -> bytes:
    if _session_secret is None:
        return ensure_session_secret()
    return _session_secret
