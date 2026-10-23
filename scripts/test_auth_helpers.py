"""Shared auth bootstrap for integration tests (subprocess servers)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from test_http_session import HttpSession


def read_last_mail_code(mail_file: Path) -> str:
    lines = mail_file.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        raise AssertionError("no captured mail")
    return json.loads(lines[-1])["code"]


def test_server_env(db_path: Path, mail_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["STORY_VOICE_GENERATOR"] = "fake"
    env["STORY_VOICE_DB_PATH"] = str(db_path)
    env.setdefault("STORY_VOICE_SESSION_SECRET", "test-session-secret")
    env["STORY_VOICE_RESEND_COOLDOWN_SEC"] = "0"
    env["STORY_VOICE_TEST_MAIL_FILE"] = str(mail_file)
    env.pop("STORY_VOICE_SMTP_HOST", None)
    mail_file.write_text("", encoding="utf-8")
    return env


def signup_admin(
    base: str,
    mail_file: Path,
    email: str = "test-admin@example.com",
    nickname: str = "테스트운영",
    password: str = "testpass12",
) -> HttpSession:
    s = HttpSession(base)
    s.fetch_config()
    code, _, _ = s.post_json("/api/users/signup/send-verification", {"loginId": email})
    assert code == 204, f"send-verification failed: {code}"
    verification = read_last_mail_code(mail_file)
    status, data, _ = s.post_json(
        "/api/users/signup",
        {
            "loginId": email,
            "nickname": nickname,
            "password": password,
            "verificationCode": verification,
        },
    )
    assert status == 201, data
    assert data and data["user"]["canWrite"] is True
    s.fetch_config()
    status, data, _ = s.post_json(
        "/api/auth/login",
        {"loginId": email, "password": password},
    )
    assert status == 200, data
    s.fetch_config()
    return s


def auth_headers(session: HttpSession) -> dict[str, str]:
    hdrs: dict[str, str] = {}
    if session.cookies:
        hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    if session.csrf:
        hdrs["X-CSRF-Token"] = session.csrf
    return hdrs
