#!/usr/bin/env python3
"""Per-user voice/audio isolation (fake generator)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from test_auth_helpers import auth_headers, save_voice_for_session, signup_member, test_server_env
PORT = 18768


def http(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    url = f"http://127.0.0.1:{PORT}{path}"
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=60)


def wait_job_done(hdrs: dict) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        st = json.loads(http("GET", "/api/generation/status", headers=hdrs).read().decode())
        recent = st.get("recent") or []
        if recent and recent[0].get("state") == "done":
            return
        if recent and recent[0].get("state") == "failed":
            raise AssertionError(recent[0].get("error"))
        time.sleep(0.3)
    raise AssertionError("generation timed out")


def test_member_voice_and_audio_isolation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mail_file = tmp_path / "mail.jsonl"
        env = test_server_env(tmp_path / "auth.db", mail_file, admin_emails="")
        users_root = Path(env["STORY_VOICE_USERS_DIR"])
        env["STORY_VOICE_VOICE_ASR"] = "fake"
        env["STORY_VOICE_FAKE_ASR_TEXT"] = "가" * 40
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(PORT), "--generator", "fake"],
            cwd=ROOT,
            env=env,
        )
        try:
            deadline = time.time() + 12
            while time.time() < deadline:
                try:
                    http("GET", "/api/config")
                    break
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(0.2)
            else:
                raise RuntimeError("server did not start")

            member_a = signup_member(
                f"http://127.0.0.1:{PORT}",
                mail_file,
                "a@example.com",
                "회원A",
            )
            member_b = signup_member(
                f"http://127.0.0.1:{PORT}",
                mail_file,
                "b@example.com",
                "회원B",
            )
            hdrs_a = auth_headers(member_a)
            hdrs_b = auth_headers(member_b)

            save_voice_for_session(member_a, "가" * 40)

            res = http(
                "POST",
                "/api/generation/story/ui-joeun-hyeongje",
                data=b'{"asrVerify":false}',
                headers={"Content-Type": "application/json", **hdrs_a},
            )
            assert res.status == 202
            wait_job_done(hdrs_a)

            from auth_db import AuthDatabase

            auth_db = AuthDatabase(tmp_path / "auth.db")
            row_a = auth_db.get_user_by_email("a@example.com")
            row_b = auth_db.get_user_by_email("b@example.com")
            assert row_a and row_b
            uid_a = row_a.id
            uid_b = row_b.id
            assert (users_root / str(uid_a) / "audio" / "ui-joeun-hyeongje.m4a").is_file()
            assert not (users_root / str(uid_b) / "audio" / "ui-joeun-hyeongje.m4a").is_file()

            cat_b = json.loads(http("GET", "/api/catalog", headers=hdrs_b).read().decode())
            story_b = next(s for s in cat_b["stories"] if s["id"] == "ui-joeun-hyeongje")
            assert story_b["hasAudio"] is True
            assert story_b["audioSource"] == "default"
            assert story_b["hasPersonalAudio"] is False

            http("GET", "/audio/ui-joeun-hyeongje.m4a", headers=hdrs_b)

            cat_a = json.loads(http("GET", "/api/catalog", headers=hdrs_a).read().decode())
            story_a = next(s for s in cat_a["stories"] if s["id"] == "ui-joeun-hyeongje")
            assert story_a["audioSource"] == "personal"

            http("GET", "/audio/ui-joeun-hyeongje.m4a", headers=hdrs_a)

            job = json.loads(
                http(
                    "POST",
                    "/api/generation/story/ui-joeun-hyeongje",
                    data=b"{}",
                    headers={"Content-Type": "application/json", **hdrs_a},
                ).read().decode()
            )
            assert job.get("deduplicated") is True or job.get("job")

        finally:
            proc.terminate()
            proc.wait(timeout=5)


def main() -> int:
    test_member_voice_and_audio_isolation()
    print("OK: per-user audio isolation tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
