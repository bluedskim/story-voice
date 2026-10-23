"""Auth business logic (signup, login, sessions)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time

from auth_config import session_secret_bytes
from auth_db import USER_TYPE_ADMIN, USER_TYPE_MEMBER, AuthDatabase, UserRow
from auth_email import EmailSendError, send_verification_email
from auth_password import hash_password, verify_password
from rate_limit import RateLimiter

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NICKNAME_RE = re.compile(r"^[a-zA-Z0-9_가-힣]{2,12}$")

VERIFICATION_TTL_SEC = 600
VERIFICATION_MAX_ATTEMPTS = 5
def _resend_cooldown_sec() -> int:
    raw = os.environ.get("STORY_VOICE_RESEND_COOLDOWN_SEC", "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return 60
SESSION_TTL_SEC = 30 * 24 * 3600

send_code_email_limit = RateLimiter(max_events=3, window_sec=3600.0)
send_code_ip_limit = RateLimiter(max_events=10, window_sec=3600.0)
verify_attempt_limit = RateLimiter(max_events=20, window_sec=600.0)


class AuthError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "auth_error",
        status: int = 400,
        retry_after_sec: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after_sec = retry_after_sec


def admin_emails() -> set[str]:
    raw = os.environ.get("STORY_VOICE_ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def resolve_user_type(email: str, db: AuthDatabase) -> str:
    if db.user_count() == 0:
        return USER_TYPE_ADMIN
    if email.lower() in admin_emails():
        return USER_TYPE_ADMIN
    return USER_TYPE_MEMBER


def user_public(user: UserRow) -> dict:
    is_admin = user.user_type == USER_TYPE_ADMIN
    return {
        "email": user.email,
        "nickname": user.nickname,
        "role": USER_TYPE_ADMIN if is_admin else USER_TYPE_MEMBER,
        "roleLabel": "운영자" if is_admin else "회원",
        "isAdmin": is_admin,
        "canWrite": is_admin,
    }


def normalize_email(login_id: str) -> str:
    email = login_id.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("올바른 이메일 주소를 입력해 주세요.", "invalid_email")
    return email


def validate_nickname(nickname: str) -> str:
    nickname = nickname.strip()
    if not NICKNAME_RE.match(nickname):
        raise AuthError(
            "닉네임은 2~12자 (영문, 숫자, _, 한글)만 사용할 수 있어요.",
            "invalid_nickname",
        )
    return nickname


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise AuthError("비밀번호는 8자 이상이어야 해요.", "weak_password")


def _hash_code(code: str) -> str:
    secret = session_secret_bytes()
    return hmac.new(secret, code.encode("utf-8"), hashlib.sha256).hexdigest()


def _hash_session_token(token: str) -> str:
    secret = session_secret_bytes()
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def nickname_available(db: AuthDatabase, nickname: str) -> bool:
    validate_nickname(nickname)
    return db.nickname_available(nickname)


def send_verification(db: AuthDatabase, login_id: str, client_ip: str) -> None:
    email = normalize_email(login_id)
    if db.email_exists(email):
        raise AuthError("이미 가입된 이메일이에요.", "email_taken", 409)
    now = time.time()
    existing = db.get_verification(email)
    if existing:
        _, _, sent_at, _ = existing
        elapsed = now - sent_at
        cooldown = _resend_cooldown_sec()
        if cooldown and elapsed < cooldown:
            wait = int(cooldown - elapsed)
            raise AuthError(
                f"잠시 후 다시 요청해 주세요. ({wait}초)",
                "cooldown",
                429,
                retry_after_sec=wait,
            )
    if not send_code_email_limit.allow(email):
        raise AuthError("인증코드 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.", "rate_limit", 429)
    if not send_code_ip_limit.allow(client_ip):
        raise AuthError("요청이 너무 많아요. 잠시 후 다시 시도해 주세요.", "rate_limit", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = now + VERIFICATION_TTL_SEC
    try:
        send_verification_email(email, code)
    except EmailSendError:
        raise AuthError(
            "인증 메일을 보내지 못했어요. 잠시 후 다시 시도해 주세요.",
            "email_send_failed",
            502,
        )
    db.save_verification(email, _hash_code(code), expires, now)


def signup(
    db: AuthDatabase,
    login_id: str,
    nickname: str,
    password: str,
    verification_code: str,
    client_ip: str,
) -> UserRow:
    email = normalize_email(login_id)
    nickname = validate_nickname(nickname)
    validate_password(password)
    if not nickname_available(db, nickname):
        raise AuthError("이미 사용 중인 닉네임이에요.", "nickname_taken", 409)
    if db.email_exists(email):
        raise AuthError("이미 가입된 이메일이에요.", "email_taken", 409)
    if not verify_attempt_limit.allow(client_ip):
        raise AuthError("시도 횟수가 너무 많아요. 잠시 후 다시 시도해 주세요.", "rate_limit", 429)

    rec = db.get_verification(email)
    if not rec:
        raise AuthError("인증코드를 먼저 요청해 주세요.", "no_verification", 400)
    code_hash, expires_at, _sent_at, failed = rec
    if time.time() > expires_at:
        db.delete_verification(email)
        raise AuthError("인증코드가 만료됐어요. 다시 요청해 주세요.", "expired_code", 400)
    if failed >= VERIFICATION_MAX_ATTEMPTS:
        raise AuthError("인증 시도 횟수를 초과했어요. 코드를 다시 요청해 주세요.", "too_many_attempts", 400)
    if _hash_code(verification_code.strip()) != code_hash:
        db.bump_verification_failed(email)
        raise AuthError("인증코드가 맞지 않아요.", "invalid_code", 400)

    db.delete_verification(email)
    user_type = resolve_user_type(email, db)
    return db.create_user(email, nickname, hash_password(password), user_type)


def login(db: AuthDatabase, login_id: str, password: str) -> tuple[str, UserRow]:
    email = normalize_email(login_id)
    user = db.get_user_by_email(email)
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("이메일 또는 비밀번호가 맞지 않아요.", "invalid_credentials", 401)
    token = secrets.token_urlsafe(32)
    expires = time.time() + SESSION_TTL_SEC
    db.create_session(_hash_session_token(token), user.id, expires)
    return token, user


def logout(db: AuthDatabase, session_token: str | None) -> None:
    if not session_token:
        return
    db.delete_session(_hash_session_token(session_token))


def user_from_session(db: AuthDatabase, session_token: str | None) -> UserRow | None:
    if not session_token:
        return None
    db.purge_expired_sessions()
    uid = db.get_session_user_id(_hash_session_token(session_token))
    if uid is None:
        return None
    return db.get_user_by_id(uid)
