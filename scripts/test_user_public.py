#!/usr/bin/env python3
"""Public session user payload must not leak operator identity."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from auth_db import USER_TYPE_MEMBER, UserRow
from auth_service import user_is_admin, user_public


def test_user_public_shape() -> None:
    user = UserRow(
        id=1,
        email="admin@example.com",
        nickname="닉",
        password_hash="x",
        user_type=USER_TYPE_MEMBER,
        created_at=0.0,
    )
    pub = user_public(user)
    assert pub == {"nickname": "닉", "canWrite": True}
    forbidden = {"email", "userId", "isAdmin", "role", "roleLabel"}
    assert forbidden.isdisjoint(pub.keys())


def test_user_is_admin_still_server_side() -> None:
    import os

    user = UserRow(
        id=1,
        email="ops@example.com",
        nickname="ops",
        password_hash="x",
        user_type=USER_TYPE_MEMBER,
        created_at=0.0,
    )
    old = os.environ.get("STORY_VOICE_ADMIN_EMAILS")
    os.environ["STORY_VOICE_ADMIN_EMAILS"] = "ops@example.com"
    try:
        assert user_is_admin(user) is True
        assert "isAdmin" not in user_public(user)
    finally:
        if old is None:
            os.environ.pop("STORY_VOICE_ADMIN_EMAILS", None)
        else:
            os.environ["STORY_VOICE_ADMIN_EMAILS"] = old


def main() -> int:
    test_user_public_shape()
    test_user_is_admin_still_server_side()
    print("OK: user_public tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
