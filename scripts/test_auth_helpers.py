"""Shared auth bootstrap for integration tests (subprocess servers)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from test_http_session import HttpSession


def read_last_mail_code(mail_file: Path) -> str:
    lines = mail_file.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        raise AssertionError("no captured mail")
    return json.loads(lines[-1])["code"]


def ensure_default_narration_fixtures(
    *,
    voice_dir: Path | None = None,
    audio_dir: Path | None = None,
) -> None:
    """Default system voice + pre-generated default story audio for integration tests."""
    from default_narration import default_audio_dir, default_voice_dir
    from generation_backends import FIXTURE_M4A
    from story_catalog import list_stories

    root = Path(__file__).resolve().parents[1]
    record_script = (root / "content" / "record_script.txt").read_text(encoding="utf-8").strip()

    voice_dir = voice_dir or default_voice_dir()
    audio_dir = audio_dir or default_audio_dir()
    ref_wav = voice_dir / "reference.wav"
    ref_txt = voice_dir / "reference.txt"
    voice_dir.mkdir(parents=True, exist_ok=True)
    if not ref_wav.is_file():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=8",
                "-ar",
                "24000",
                "-ac",
                "1",
                str(ref_wav),
            ],
            check=True,
        )
    if not ref_txt.is_file() and record_script:
        ref_txt.write_text(record_script + "\n", encoding="utf-8")

    audio_dir.mkdir(parents=True, exist_ok=True)
    if not FIXTURE_M4A.is_file():
        FIXTURE_M4A.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                str(FIXTURE_M4A),
            ],
            check=True,
        )
    for story in list_stories():
        dest = audio_dir / f"{story.id}.m4a"
        if not dest.is_file():
            shutil.copy2(FIXTURE_M4A, dest)


def test_server_env(
    db_path: Path,
    mail_file: Path,
    admin_emails: str | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["STORY_VOICE_GENERATOR"] = "fake"
    env["STORY_VOICE_DB_PATH"] = str(db_path)
    env.setdefault("STORY_VOICE_SESSION_SECRET", "test-session-secret")
    env["STORY_VOICE_RESEND_COOLDOWN_SEC"] = "0"
    env["STORY_VOICE_TEST_MAIL_FILE"] = str(mail_file)
    env.pop("STORY_VOICE_SMTP_HOST", None)
    if admin_emails is not None:
        env["STORY_VOICE_ADMIN_EMAILS"] = admin_emails
    else:
        env.pop("STORY_VOICE_ADMIN_EMAILS", None)
    mail_file.write_text("", encoding="utf-8")
    data_root = db_path.parent
    users_root = data_root / "users"
    users_root.mkdir(parents=True, exist_ok=True)
    env["STORY_VOICE_USERS_DIR"] = str(users_root)
    env["STORY_VOICE_DEFAULT_VOICE_DIR"] = str(data_root / "voice_default")
    env["STORY_VOICE_DEFAULT_AUDIO_DIR"] = str(data_root / "audio_default")
    ensure_default_narration_fixtures(
        voice_dir=data_root / "voice_default",
        audio_dir=data_root / "audio_default",
    )
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


def signup_member(
    base: str,
    mail_file: Path,
    email: str,
    nickname: str,
    password: str = "memberpass1",
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
    assert "isAdmin" not in data["user"]
    status, data, _ = s.post_json(
        "/api/auth/login",
        {"loginId": email, "password": password},
    )
    assert status == 200, data
    s.fetch_config()
    return s


def save_voice_for_session(session: HttpSession, transcript: str | None = None) -> None:
    import subprocess
    import tempfile
    from pathlib import Path

    import json

    root = Path(__file__).resolve().parents[1]
    hdrs = auth_headers(session)
    with tempfile.TemporaryDirectory() as upload_tmp:
        wav = Path(upload_tmp) / "voice.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=12",
                "-ar",
                "24000",
                "-ac",
                "1",
                str(wav),
            ],
            check=True,
        )
        boundary = "----storyvoice"
        audio = wav.read_bytes()
        body = b"".join(
            [
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="audio"; filename="test.wav"\r\n'
                f"Content-Type: audio/wav\r\n\r\n".encode()
                + audio
                + b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        import urllib.request

        prep_req = urllib.request.Request(
            f"{session.base}/api/voice/prepare",
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                **hdrs,
            },
        )
        prep_res = urllib.request.urlopen(prep_req, timeout=60)
        prep = json.loads(prep_res.read().decode())
        asr_text = (prep.get("transcript") or "").strip()
        if transcript is not None and transcript.strip() and transcript.strip() != asr_text:
            raise AssertionError("fake ASR must match expected transcript for voice save tests")
        confirm = json.dumps(
            {"pendingToken": prep["pendingToken"], "transcript": asr_text},
            ensure_ascii=False,
        ).encode()
        conf_req = urllib.request.Request(
            f"{session.base}/api/voice/confirm",
            data=confirm,
            method="POST",
            headers={"Content-Type": "application/json", **hdrs},
        )
        urllib.request.urlopen(conf_req, timeout=60)


def auth_headers(session: HttpSession) -> dict[str, str]:
    hdrs: dict[str, str] = {}
    if session.cookies:
        hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    if session.csrf:
        hdrs["X-CSRF-Token"] = session.csrf
    return hdrs
