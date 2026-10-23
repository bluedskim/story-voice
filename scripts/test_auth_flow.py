#!/usr/bin/env python3
"""Auth signup/login, CSRF, and write-gating tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from test_auth_helpers import read_last_mail_code, test_server_env
from test_http_session import HttpSession

PORT = 18767


def start_server(db_path: Path, mail_file: Path, admin_emails: str | None = None) -> subprocess.Popen:
    env = test_server_env(db_path, mail_file, admin_emails=admin_emails)
    return subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(PORT), "--generator", "fake"],
        cwd=ROOT,
        env=env,
    )


def wait_server(sess: HttpSession, timeout: float = 12.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sess.fetch_config()
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def test_signup_login_logout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db = tmp_path / "auth.db"
        mail_file = tmp_path / "mail.jsonl"
        proc = start_server(db, mail_file)
        try:
            admin = HttpSession(f"http://127.0.0.1:{PORT}")
            wait_server(admin)
            code, _, _ = admin.post_json(
                "/api/users/signup/send-verification",
                {"loginId": "parent@example.com"},
            )
            assert code == 204
            code = read_last_mail_code(mail_file)
            status, data, _ = admin.post_json(
                "/api/users/signup",
                {
                    "loginId": "parent@example.com",
                    "nickname": "엄마",
                    "password": "secret123",
                    "verificationCode": code,
                },
            )
            assert status == 201
            assert data["user"]["isAdmin"] is False
            assert data["user"]["canWrite"] is False

            guest = HttpSession(f"http://127.0.0.1:{PORT}")
            guest.fetch_config()
            status, data, _ = guest.post_json(
                "/api/auth/login",
                {"loginId": "parent@example.com", "password": "secret123"},
            )
            assert status == 200
            assert data["user"]["nickname"] == "엄마"
            assert "sv_session" in guest.cookies

            me = json.loads(guest.request("GET", "/api/auth/me").read().decode())
            assert me["user"]["email"] == "parent@example.com"

            status, _, _ = guest.post_json("/api/auth/logout", {})
            assert status == 200
            me2 = json.loads(guest.request("GET", "/api/auth/me").read().decode())
            assert me2["user"] is None
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_nickname_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        proc = start_server(tmp_path / "auth.db", tmp_path / "mail.jsonl")
        try:
            s = HttpSession(f"http://127.0.0.1:{PORT}")
            wait_server(s)
            q = urllib.parse.urlencode({"nickname": "새닉"})
            res = s.request("GET", f"/api/users/nickname-available?{q}")
            data = json.loads(res.read().decode())
            assert data["available"] is True
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_gating_and_csrf() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db = tmp_path / "auth.db"
        mail_file = tmp_path / "mail.jsonl"
        proc = start_server(db, mail_file, admin_emails="admin@example.com")
        try:
            s = HttpSession(f"http://127.0.0.1:{PORT}")
            wait_server(s)
            # no CSRF
            try:
                s.csrf = ""
                s.post_json("/api/auth/login", {"loginId": "a@b.com", "password": "x"})
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
            s.fetch_config()

            status, data, _ = s.post_json("/api/generation/story/ui-joeun-hyeongje", {})
            assert status == 401
            assert data.get("code") == "auth_required"

            s.fetch_config()
            s.post_json("/api/users/signup/send-verification", {"loginId": "admin@example.com"})
            code = read_last_mail_code(mail_file)
            status_admin, data_admin, _ = s.post_json(
                "/api/users/signup",
                {
                    "loginId": "admin@example.com",
                    "nickname": "관리자",
                    "password": "adminpass1",
                    "verificationCode": code,
                },
            )
            assert status_admin == 201
            assert data_admin["user"]["isAdmin"] is True
            assert data_admin["user"]["canWrite"] is True

            s.fetch_config()
            s.post_json("/api/users/signup/send-verification", {"loginId": "kid@example.com"})
            code2 = read_last_mail_code(mail_file)
            s.post_json(
                "/api/users/signup",
                {
                    "loginId": "kid@example.com",
                    "nickname": "아이",
                    "password": "kidpass12",
                    "verificationCode": code2,
                },
            )

            kid = HttpSession(f"http://127.0.0.1:{PORT}")
            kid.fetch_config()
            status, data, _ = kid.post_json(
                "/api/auth/login",
                {"loginId": "kid@example.com", "password": "kidpass12"},
            )
            assert status == 200
            assert data["user"]["canWrite"] is False
            kid.fetch_config()
            status, data, _ = kid.post_json("/api/generation/all", {})
            assert status == 403
            assert data.get("code") == "forbidden"
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_admin_role_follows_env_list() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db = tmp_path / "auth.db"
        mail_file = tmp_path / "mail.jsonl"
        email = "role@example.com"
        password = "rolepass12"
        proc = start_server(db, mail_file, admin_emails="")
        try:
            s = HttpSession(f"http://127.0.0.1:{PORT}")
            wait_server(s)
            s.post_json("/api/users/signup/send-verification", {"loginId": email})
            code = read_last_mail_code(mail_file)
            status, data, _ = s.post_json(
                "/api/users/signup",
                {
                    "loginId": email,
                    "nickname": "역할",
                    "password": password,
                    "verificationCode": code,
                },
            )
            assert status == 201
            assert data["user"]["canWrite"] is False
        finally:
            proc.terminate()
            proc.wait(timeout=5)

        proc2 = start_server(db, mail_file, admin_emails=email)
        try:
            s2 = HttpSession(f"http://127.0.0.1:{PORT}")
            wait_server(s2)
            status, data, _ = s2.post_json(
                "/api/auth/login",
                {"loginId": email, "password": password},
            )
            assert status == 200
            assert data["user"]["canWrite"] is True
            me = json.loads(s2.request("GET", "/api/auth/me").read().decode())
            assert me["user"]["isAdmin"] is True
        finally:
            proc2.terminate()
            proc2.wait(timeout=5)

        proc3 = start_server(db, mail_file, admin_emails="")
        try:
            s3 = HttpSession(f"http://127.0.0.1:{PORT}")
            wait_server(s3)
            s3.fetch_config()
            status, data, _ = s3.post_json(
                "/api/auth/login",
                {"loginId": email, "password": password},
            )
            assert status == 200
            assert data["user"]["canWrite"] is False
            status, data, _ = s3.post_json("/api/generation/all", {})
            assert status == 403
            assert data.get("code") == "forbidden"
        finally:
            proc3.terminate()
            proc3.wait(timeout=5)


def test_rate_limit_send_verification() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        proc = start_server(tmp_path / "auth.db", tmp_path / "mail.jsonl")
        try:
            s = HttpSession(f"http://127.0.0.1:{PORT}")
            wait_server(s)
            email = "rate@example.com"
            for _ in range(3):
                s.fetch_config()
                code, _, _ = s.post_json("/api/users/signup/send-verification", {"loginId": email})
                assert code == 204
            s.fetch_config()
            status, data, _ = s.post_json("/api/users/signup/send-verification", {"loginId": email})
            assert status == 429
            assert data.get("code") == "rate_limit"
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def main() -> int:
    test_signup_login_logout()
    test_nickname_available()
    test_gating_and_csrf()
    test_admin_role_follows_env_list()
    test_rate_limit_send_verification()
    print("OK: auth flow tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
