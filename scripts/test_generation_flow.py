#!/usr/bin/env python3
"""Integration tests without MLX (STORY_VOICE_GENERATOR=fake)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from test_auth_helpers import auth_headers, signup_admin, test_server_env

PORT = 18765


def http(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    url = f"http://127.0.0.1:{PORT}{path}"
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=30)


def wait_server(timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            http("GET", "/api/config")
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def make_upload_wav(path: Path, duration: float = 8.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
    )


def multipart_upload(transcript: str, file_bytes: bytes, filename: str, content_type: str) -> bytes:
    boundary = "----storyvoice"
    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="transcript"\r\n\r\n'
        f"{transcript}\r\n",
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
        + file_bytes
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join([p if isinstance(p, bytes) else p.encode() for p in parts])


def multipart_audio_only(wav_path: Path) -> bytes:
    boundary = "----storyvoice"
    audio = wav_path.read_bytes()
    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="test.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode()
        + audio
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts)


def multipart_voice(wav_path: Path, transcript: str) -> bytes:
    boundary = "----storyvoice"
    audio = wav_path.read_bytes()
    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="transcript"\r\n\r\n'
        f"{transcript}\r\n",
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="test.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode()
        + audio
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join([p if isinstance(p, bytes) else p.encode() for p in parts])
    return body


def test_generation_asr_enqueue_flags() -> None:
    import os

    from generation_backends import FakeGenerationBackend
    from generation_service import GenerationService

    old = os.environ.get("STORY_VOICE_ASR_VERIFY")
    try:
        os.environ["STORY_VOICE_ASR_VERIFY"] = "1"
        off = GenerationService(backend=FakeGenerationBackend()).enqueue_story(
            "ui-joeun-hyeongje", 1, asr_verify_request=False
        )
        assert off.job.asr_verify is False
        env_default = GenerationService(backend=FakeGenerationBackend()).enqueue_story(
            "ui-joeun-hyeongje", 1, asr_verify_request=None
        )
        assert env_default.job.asr_verify is True
        on = GenerationService(backend=FakeGenerationBackend()).enqueue_story(
            "ui-joeun-hyeongje", 1, asr_verify_request=True
        )
        assert on.job.asr_verify is True
    finally:
        if old is None:
            os.environ.pop("STORY_VOICE_ASR_VERIFY", None)
        else:
            os.environ["STORY_VOICE_ASR_VERIFY"] = old


def test_generate_all_removed() -> None:
    from generation_service import GenerationService

    assert not hasattr(GenerationService, "enqueue_all"), "bulk generate-all must stay removed"


def test_download_filename_helpers() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from download_filenames import (
        content_disposition_attachment,
        download_basename,
        sanitize_title_for_filename,
    )

    kst = datetime(2026, 10, 21, 8, 30, 45, tzinfo=ZoneInfo("Asia/Seoul"))
    assert sanitize_title_for_filename('의좋은/형제') == "의좋은형제"
    assert download_basename("의좋은 형제", kst) == "의좋은 형제_20261021-083045.m4a"
    cd = content_disposition_attachment("의좋은 형제_20261021-083045.m4a", "ui-joeun-hyeongje_20261021-083045.m4a")
    assert "attachment" in cd
    assert "filename*=" in cd
    assert "UTF-8''" in cd
    assert "%EC%9D%98" in cd  # UTF-8 percent-encoded '의'


def main() -> int:
    test_download_filename_helpers()
    test_generation_asr_enqueue_flags()
    test_generate_all_removed()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db = tmp_path / "auth.db"
        mail_file = tmp_path / "mail.jsonl"
        env = test_server_env(db, mail_file, admin_emails="test-admin@example.com")
        users_root = Path(env["STORY_VOICE_USERS_DIR"])
        env["STORY_VOICE_VOICE_ASR"] = "fake"
        script = (ROOT / "content" / "record_script.txt").read_text(encoding="utf-8").strip()
        env["STORY_VOICE_FAKE_ASR_TEXT"] = script
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(PORT), "--generator", "fake"],
            cwd=ROOT,
            env=env,
        )
        try:
            wait_server()
            admin = signup_admin(f"http://127.0.0.1:{PORT}", mail_file)
            write_hdrs = auth_headers(admin)

            from http_utils import parse_multipart_body

            parsed = parse_multipart_body(
                multipart_upload(script, b"hello", "x.txt", "text/plain"),
                "multipart/form-data; boundary=----storyvoice",
            )
            assert parsed and parsed.get("transcript") == script

            try:
                http(
                    "POST",
                    "/api/voice/prepare",
                    data=multipart_upload(script, b"not audio", "x.bin", "application/octet-stream"),
                    headers={
                        "Content-Type": "multipart/form-data; boundary=----storyvoice",
                        **write_hdrs,
                    },
                )
                raise AssertionError("expected 400 for non-audio")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
                err = json.loads(exc.read().decode())
                assert err.get("code") == "invalid_audio"

            with tempfile.TemporaryDirectory() as wav_tmp:
                wav = Path(wav_tmp) / "voice.wav"
                make_upload_wav(wav, 12.0)
                prep_body = multipart_audio_only(wav)
                res = http(
                    "POST",
                    "/api/voice/prepare",
                    data=prep_body,
                    headers={
                        "Content-Type": "multipart/form-data; boundary=----storyvoice",
                        **write_hdrs,
                    },
                )
                assert res.status == 200
                prep = json.loads(res.read().decode())
                confirm = json.dumps(
                    {"pendingToken": prep["pendingToken"], "transcript": prep.get("transcript") or script},
                    ensure_ascii=False,
                ).encode()
                res = http(
                    "POST",
                    "/api/voice/confirm",
                    data=confirm,
                    headers={"Content-Type": "application/json", **write_hdrs},
                )
                assert res.status == 200

            from auth_db import AuthDatabase

            row = AuthDatabase(db).get_user_by_email("test-admin@example.com")
            assert row is not None
            admin_uid = row.id
            ref = users_root / str(admin_uid) / "voice" / "reference.wav"
            assert ref.is_file(), "reference.wav missing"

            try:
                http(
                    "POST",
                    "/api/generation/story/does-not-exist",
                    data=b"{}",
                    headers={"Content-Type": "application/json", **write_hdrs},
                )
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404

            try:
                http(
                    "POST",
                    "/api/generation/story/ui-joeun-hyeongje",
                    data=b'{"asrVerify":"yes"}',
                    headers={"Content-Type": "application/json", **write_hdrs},
                )
                raise AssertionError("expected 400 for bad asrVerify")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400

            res = http(
                "POST",
                "/api/generation/story/ui-joeun-hyeongje",
                data=b'{"asrVerify":false}',
                headers={"Content-Type": "application/json", **write_hdrs},
            )
            assert res.status == 202
            first = json.loads(res.read().decode())
            job_id = first["job"]["jobId"]
            assert first["job"].get("asrVerify") is False

            res2 = http(
                "POST",
                "/api/generation/story/ui-joeun-hyeongje",
                data=b"{}",
                headers={"Content-Type": "application/json", **write_hdrs},
            )
            dup = json.loads(res2.read().decode())
            assert dup.get("deduplicated") is True
            assert dup["job"]["jobId"] == job_id

            deadline = time.time() + 60
            while time.time() < deadline:
                st = json.loads(http("GET", "/api/generation/status").read().decode())
                recent = st.get("recent") or []
                if recent and recent[0].get("state") == "done":
                    break
                if recent and recent[0].get("state") == "failed":
                    raise AssertionError(recent[0].get("error"))
                time.sleep(0.3)
            else:
                raise AssertionError("generation timed out")

            out = users_root / str(admin_uid) / "audio" / "ui-joeun-hyeongje.m4a"
            assert out.is_file(), "output m4a missing"

            cat = json.loads(http("GET", "/api/catalog", headers=write_hdrs).read().decode())
            assert any(s["id"] == "ui-joeun-hyeongje" and s["hasAudio"] for s in cat["stories"])

            res = http("GET", "/audio/ui-joeun-hyeongje.m4a", headers={"Range": "bytes=0-99", **write_hdrs})
            assert res.status == 206, res.status
            assert res.headers.get("Content-Type") == "audio/mp4"
            assert res.headers.get("Content-Disposition") is None

            res = http("GET", "/audio/ui-joeun-hyeongje.m4a?download=1", headers=write_hdrs)
            assert res.status == 200
            cd = res.headers.get("Content-Disposition", "")
            assert "attachment" in cd
            assert "filename*=" in cd
            assert "UTF-8''" in cd
            assert "의좋은" in cd or "%EC%9D%98" in cd

            try:
                http("GET", "/audio/does-not-exist.m4a?download=1")
                raise AssertionError("expected 404 without login for unknown story")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            try:
                http(
                    "GET",
                    "/audio/does-not-exist.m4a?download=1",
                    headers=write_hdrs,
                )
                raise AssertionError("expected 404 for unknown download")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404

            try:
                http("GET", "/audio/")
                raise AssertionError("expected 404 for /audio/")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404

            print(
                "OK: download filenames, multipart, bad upload 400, unknown story 404, dedupe, "
                "voice upload, fake generation, range playback vs download disposition, no listing"
            )
            return 0
        finally:
            proc.terminate()
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
