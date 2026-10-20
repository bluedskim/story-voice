#!/usr/bin/env python3
"""Voice prepare/confirm flow (fake ASR, no MLX)."""

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

PORT = 18766


def http(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    url = f"http://127.0.0.1:{PORT}{path}"
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=60)


def wait_server(timeout: float = 12.0) -> None:
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
            "24000",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
    )


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


def test_duration_text_bounds_unit() -> None:
    from voice_service import VoiceSaveError, validate_text_fits_duration

    validate_text_fits_duration("가" * 20, 8.0)
    try:
        validate_text_fits_duration("가" * 140, 8.0)
        raise AssertionError("expected reject for 8s / 140 chars")
    except VoiceSaveError as exc:
        assert exc.code == "text_too_long_for_audio"


def test_prepare_and_confirm_integration() -> None:
    from voice_service import REF_TXT, REF_WAV

    env = os.environ.copy()
    env["STORY_VOICE_GENERATOR"] = "fake"
    env["STORY_VOICE_VOICE_ASR"] = "fake"
    short_asr = "가" * 40
    env["STORY_VOICE_FAKE_ASR_TEXT"] = short_asr
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(PORT), "--generator", "fake"],
        cwd=ROOT,
        env=env,
    )
    try:
        wait_server()
        REF_WAV.parent.mkdir(parents=True, exist_ok=True)
        REF_TXT.write_text("기존 참조 텍스트\n", encoding="utf-8")
        if REF_WAV.is_file():
            REF_WAV.unlink()
        make_upload_wav(REF_WAV, 8.0)

        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "upload.wav"
            make_upload_wav(wav, 8.0)
            res = http(
                "POST",
                "/api/voice/prepare",
                data=multipart_audio_only(wav),
                headers={"Content-Type": "multipart/form-data; boundary=----storyvoice"},
            )
            assert res.status == 200
            prep = json.loads(res.read().decode())
            assert prep.get("pendingToken")
            assert prep.get("transcript") == short_asr
            assert REF_TXT.read_text(encoding="utf-8").startswith("기존")

            confirm_body = json.dumps(
                {"pendingToken": prep["pendingToken"], "transcript": short_asr},
                ensure_ascii=False,
            ).encode("utf-8")
            res2 = http(
                "POST",
                "/api/voice/confirm",
                data=confirm_body,
                headers={"Content-Type": "application/json"},
            )
            assert res2.status == 200
            assert REF_TXT.read_text(encoding="utf-8").strip() == short_asr
            assert REF_WAV.is_file()
            history = list((ROOT / "data" / "voice" / "history").glob("*"))
            assert history, "expected backup dir"

        # expired token
        try:
            http(
                "POST",
                "/api/voice/confirm",
                data=json.dumps({"pendingToken": "invalid-token", "transcript": "테스트"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            raise AssertionError("expected gone for bad token")
        except urllib.error.HTTPError as exc:
            assert exc.code in {400, 410, 404}

    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_confirm_rejects_long_text_for_short_audio() -> None:
    from voice_pending import create_pending, delete_pending
    from voice_service import VoiceSaveError, confirm_voice_upload

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "ref.wav"
        make_upload_wav(wav, 8.0)
        pending = create_pending(wav, 8.0, "가" * 40, "expected", 0.1)
        try:
            confirm_voice_upload(pending.token, "가" * 140)
            raise AssertionError("expected reject")
        except VoiceSaveError as exc:
            assert exc.code == "text_too_long_for_audio"
        finally:
            delete_pending(pending.token)


def test_prepare_blocked_during_generation() -> None:
    env = os.environ.copy()
    env["STORY_VOICE_GENERATOR"] = "fake"
    env["STORY_VOICE_VOICE_ASR"] = "fake"
    env["STORY_VOICE_FAKE_CHUNK_DELAY"] = "30"
    env["STORY_VOICE_FAKE_ASR_TEXT"] = "테스트"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(PORT), "--generator", "fake"],
        cwd=ROOT,
        env=env,
    )
    try:
        wait_server()
        http("POST", "/api/generation/story/ui-joeun-hyeongje")
        time.sleep(0.5)
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "v.wav"
            make_upload_wav(wav, 8.0)
            try:
                http(
                    "POST",
                    "/api/voice/prepare",
                    data=multipart_audio_only(wav),
                    headers={"Content-Type": "multipart/form-data; boundary=----storyvoice"},
                )
                raise AssertionError("expected 409 during generation")
            except urllib.error.HTTPError as exc:
                assert exc.code == 409
                err = json.loads(exc.read().decode())
                assert err.get("code") == "generation_busy"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def main() -> int:
    test_duration_text_bounds_unit()
    test_prepare_and_confirm_integration()
    test_confirm_rejects_long_text_for_short_audio()
    test_prepare_blocked_during_generation()
    print("OK: voice upload flow tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
