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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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


def main() -> int:
    os.environ["STORY_VOICE_GENERATOR"] = "fake"
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(PORT), "--generator", "fake"],
        cwd=ROOT,
        env=env,
    )
    try:
        wait_server()

        # Voice upload
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "voice.wav"
            make_upload_wav(wav, 8.0)
            script = (ROOT / "content" / "record_script.txt").read_text(encoding="utf-8").strip()
            body = multipart_voice(wav, script)
            res = http(
                "POST",
                "/api/voice",
                data=body,
                headers={"Content-Type": "multipart/form-data; boundary=----storyvoice"},
            )
            assert res.status == 200, res.read()

        ref = ROOT / "data" / "voice" / "reference.wav"
        assert ref.is_file(), "reference.wav missing"

        # Enqueue one story
        res = http("POST", "/api/generation/story/ui-joeun-hyeongje")
        assert res.status == 202

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

        out = ROOT / "data" / "audio" / "ui-joeun-hyeongje.m4a"
        assert out.is_file(), "output m4a missing"

        # Catalog whitelist refresh (no restart)
        cat = json.loads(http("GET", "/catalog.json").read().decode())
        assert any(s["id"] == "ui-joeun-hyeongje" and s["hasAudio"] for s in cat["stories"])

        res = http("GET", "/audio/ui-joeun-hyeongje.m4a", headers={"Range": "bytes=0-99"})
        assert res.status == 206, res.status
        assert res.headers.get("Content-Type") == "audio/mp4"

        try:
            http("GET", "/audio/")
            raise AssertionError("expected 404 for /audio/")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404

        print("OK: voice upload, fake generation, atomic replace, range, no listing")
        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
