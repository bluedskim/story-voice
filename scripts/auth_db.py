"""SQLite user/session store for story-voice."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

USER_TYPE_MEMBER = "member"
USER_TYPE_ADMIN = "admin"


def db_path() -> Path:
    raw = os.environ.get("STORY_VOICE_DB_PATH", "").strip()
    if raw:
        return Path(raw)
    return ROOT / "data" / "story_voice.db"


@dataclass(frozen=True)
class UserRow:
    id: int
    email: str
    nickname: str
    password_hash: str
    user_type: str
    created_at: float

    @property
    def is_admin(self) -> bool:
        from auth_service import user_is_admin

        return user_is_admin(self)


class AuthDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                        nickname TEXT NOT NULL COLLATE NOCASE UNIQUE,
                        password_hash TEXT NOT NULL,
                        user_type TEXT NOT NULL DEFAULT 'member',
                        created_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sessions (
                        token_hash TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        expires_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS email_verifications (
                        email TEXT NOT NULL COLLATE NOCASE PRIMARY KEY,
                        code_hash TEXT NOT NULL,
                        expires_at REAL NOT NULL,
                        sent_at REAL NOT NULL,
                        failed_attempts INTEGER NOT NULL DEFAULT 0
                    );
                    """
                )
                cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
                if "is_admin" in cols and "user_type" not in cols:
                    conn.execute("ALTER TABLE users ADD COLUMN user_type TEXT NOT NULL DEFAULT 'member'")
                    conn.execute(
                        "UPDATE users SET user_type = ? WHERE is_admin = 1",
                        (USER_TYPE_ADMIN,),
                    )
                ev_cols = {row[1] for row in conn.execute("PRAGMA table_info(email_verifications)").fetchall()}
                if "sent_at" not in ev_cols:
                    conn.execute("ALTER TABLE email_verifications ADD COLUMN sent_at REAL")
                    conn.execute(
                        "UPDATE email_verifications SET sent_at = created_at "
                        "WHERE sent_at IS NULL AND created_at IS NOT NULL"
                    )
                if "failed_attempts" not in ev_cols and "attempts" in ev_cols:
                    conn.execute(
                        "ALTER TABLE email_verifications ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0"
                    )
                    conn.execute("UPDATE email_verifications SET failed_attempts = attempts")
                conn.commit()
            finally:
                conn.close()

    def user_count(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
                return int(row["c"])
            finally:
                conn.close()

    def nickname_available(self, nickname: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM users WHERE nickname = ? COLLATE NOCASE",
                    (nickname,),
                ).fetchone()
                return row is None
            finally:
                conn.close()

    def email_exists(self, email: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE",
                    (email,),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def create_user(self, email: str, nickname: str, password_hash: str, user_type: str) -> UserRow:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO users (email, nickname, password_hash, user_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (email, nickname, password_hash, user_type, now),
                )
                conn.commit()
                uid = int(cur.lastrowid)
                return UserRow(uid, email, nickname, password_hash, user_type, now)
            finally:
                conn.close()

    def get_user_by_email(self, email: str) -> UserRow | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
                    (email,),
                ).fetchone()
                return _row_to_user(row) if row else None
            finally:
                conn.close()

    def get_user_by_id(self, user_id: int) -> UserRow | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                return _row_to_user(row) if row else None
            finally:
                conn.close()

    def save_verification(self, email: str, code_hash: str, expires_at: float, sent_at: float) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO email_verifications (email, code_hash, expires_at, sent_at, failed_attempts)
                    VALUES (?, ?, ?, ?, 0)
                    ON CONFLICT(email) DO UPDATE SET
                        code_hash=excluded.code_hash,
                        expires_at=excluded.expires_at,
                        sent_at=excluded.sent_at,
                        failed_attempts=0
                    """,
                    (email, code_hash, expires_at, sent_at),
                )
                conn.commit()
            finally:
                conn.close()

    def get_verification(self, email: str) -> tuple[str, float, float, int] | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT code_hash, expires_at, sent_at, failed_attempts
                    FROM email_verifications WHERE email = ? COLLATE NOCASE
                    """,
                    (email,),
                ).fetchone()
                if not row:
                    return None
                return (
                    str(row["code_hash"]),
                    float(row["expires_at"]),
                    float(row["sent_at"] or 0),
                    int(row["failed_attempts"] or 0),
                )
            finally:
                conn.close()

    def bump_verification_failed(self, email: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE email_verifications SET failed_attempts = failed_attempts + 1 "
                    "WHERE email = ? COLLATE NOCASE",
                    (email,),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_verification(self, email: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM email_verifications WHERE email = ? COLLATE NOCASE", (email,))
                conn.commit()
            finally:
                conn.close()

    def create_session(self, token_hash: str, user_id: int, expires_at: float) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                    (token_hash, user_id, expires_at),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_session(self, token_hash: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                conn.commit()
            finally:
                conn.close()

    def get_session_user_id(self, token_hash: str) -> int | None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
                    (token_hash,),
                ).fetchone()
                if not row:
                    return None
                if float(row["expires_at"]) < now:
                    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                    conn.commit()
                    return None
                return int(row["user_id"])
            finally:
                conn.close()

    def purge_expired_sessions(self) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
                conn.commit()
            finally:
                conn.close()


def _row_to_user(row: sqlite3.Row) -> UserRow:
    if "user_type" in row.keys():
        user_type = str(row["user_type"])
    else:
        user_type = USER_TYPE_ADMIN if bool(row["is_admin"]) else USER_TYPE_MEMBER
    return UserRow(
        id=int(row["id"]),
        email=str(row["email"]),
        nickname=str(row["nickname"]),
        password_hash=str(row["password_hash"]),
        user_type=user_type,
        created_at=float(row["created_at"]),
    )
