"""Verification email via Resend HTTP API or dev log."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from auth_config import mail_from, mail_mode, resend_api_key

LOG = logging.getLogger("story-voice.auth.email")

# Cloudflare (and some CDNs) block urllib's default client fingerprint (error 1010).
RESEND_USER_AGENT = "Story-Voice/1.0 (+https://story-voice.baem.app; mail)"

# Test hook: when set to a list, capture outbound messages instead of sending.
FAKE_OUTBOX: list[dict] | None = None


class EmailSendError(Exception):
    pass


def effective_mail_mode() -> str:
    mode = mail_mode()
    if mode == "resend" and not resend_api_key():
        return "log"
    return mode


def is_log_mail_mode() -> bool:
    return effective_mail_mode() == "log"


def _resend_email_request(api_key: str, payload: dict) -> urllib.request.Request:
    return urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": RESEND_USER_AGENT,
        },
        method="POST",
    )


def _capture_test_mail(to_email: str, code: str, subject: str) -> bool:
    path = os.environ.get("STORY_VOICE_TEST_MAIL_FILE", "").strip()
    if not path:
        return False
    record = {"to": to_email, "code": code, "subject": subject}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def send_verification_email(to_email: str, code: str) -> None:
    subject = "story-voice 인증코드"
    body = (
        f"인증코드: {code}\n\n"
        "10분 안에 회원가입 화면에 입력해 주세요.\n"
        "본인이 요청하지 않았다면 이 메일을 무시하셔도 됩니다."
    )
    if FAKE_OUTBOX is not None:
        FAKE_OUTBOX.append({"to": to_email, "code": code, "subject": subject})
        return
    if _capture_test_mail(to_email, code, subject):
        return
    if effective_mail_mode() == "log":
        LOG.warning("STORY_VOICE mail(log): %s → verification code %s", to_email, code)
        return
    api_key = resend_api_key()
    payload = {
        "from": mail_from(),
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    req = _resend_email_request(api_key, payload)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            if res.status >= 400:
                raise EmailSendError(f"resend status {res.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        LOG.error("Resend failed: %s %s", exc.code, detail)
        raise EmailSendError("resend_http_error") from exc
    except urllib.error.URLError as exc:
        LOG.error("Resend network error: %s", exc)
        raise EmailSendError("resend_network") from exc
