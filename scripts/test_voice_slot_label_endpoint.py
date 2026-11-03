#!/usr/bin/env python3
"""POST /api/voice/slots/label — rename voice slot labels."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from test_auth_helpers import signup_member, test_server_env
from test_http_session import HttpSession
from voice_slots import VoiceSlotError, create_slot, update_slot_label

PORT = 18768


def wait_server(timeout: float = 12.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/config", timeout=2)
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def test_update_slot_label_unit_validation() -> None:
    import os

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORY_VOICE_USERS_DIR"] = tmp
        uid = 5
        create_slot(uid, "시작")
        slots = update_slot_label(uid, 1, "  Dana  ")
        assert any(s["id"] == 1 and s["label"] == "Dana" for s in slots)
        try:
            update_slot_label(uid, 1, "   ")
            raise AssertionError("expected empty_label")
        except VoiceSlotError as exc:
            assert exc.code == "empty_label"
        try:
            update_slot_label(uid, 1, "가" * 21)
            raise AssertionError("expected label_too_long")
        except VoiceSlotError as exc:
            assert exc.code == "label_too_long"
        try:
            update_slot_label(uid, 99, "없음")
            raise AssertionError("expected invalid_slot")
        except VoiceSlotError as exc:
            assert exc.code == "invalid_slot"
        try:
            update_slot_label(uid, 2, "둘째")
            raise AssertionError("expected unknown_slot")
        except VoiceSlotError as exc:
            assert exc.code == "unknown_slot"


def test_label_endpoint_integration() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mail_file = tmp_path / "mail.jsonl"
        env = test_server_env(tmp_path / "auth.db", mail_file)
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(PORT), "--generator", "fake"],
            cwd=ROOT,
            env=env,
        )
        try:
            wait_server()
            base = f"http://127.0.0.1:{PORT}"
            session = signup_member(base, mail_file, "member@example.com", "멤버")
            status, data, _ = session.post_json(
                "/api/voice/slots",
                {"label": "내 목소리"},
            )
            assert status == 201, data
            slot_id = data["slot"]["id"]

            status, data, _ = session.post_json(
                "/api/voice/slots/label",
                {"slotId": slot_id, "label": "Dana"},
            )
            assert status == 200, data
            labels = {s["id"]: s["label"] for s in data["slots"]}
            assert labels[slot_id] == "Dana"

            status, data, _ = session.post_json(
                "/api/voice/slots/label",
                {"slotId": slot_id, "label": "   "},
            )
            assert status == 400, data
            assert data and data.get("code") == "empty_label"

            status, data, _ = session.post_json(
                "/api/voice/slots/label",
                {"slotId": 4, "label": "없는 슬롯"},
            )
            assert status == 400, data
            assert data and data.get("code") == "unknown_slot"

            anon = HttpSession(base)
            anon.fetch_config()
            status, data, _ = anon.post_json(
                "/api/voice/slots/label",
                {"slotId": 1, "label": "해킹"},
            )
            assert status == 401, data
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def main() -> int:
    test_update_slot_label_unit_validation()
    test_label_endpoint_integration()
    print("OK: voice slot label endpoint tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
