#!/usr/bin/env python3
"""Unit tests for Resend verification email HTTP client."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import auth_email  # noqa: E402


class ResendRequestHeadersTest(unittest.TestCase):
    def test_resend_request_includes_user_agent(self) -> None:
        req = auth_email._resend_email_request(
            "re_test_key",
            {"from": "x@y.z", "to": ["a@b.c"], "subject": "s", "text": "t"},
        )
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers.get("user-agent"), auth_email.RESEND_USER_AGENT)
        self.assertEqual(headers.get("accept"), "application/json")
        self.assertTrue(headers.get("authorization", "").startswith("Bearer "))

    def test_send_verification_uses_resend_request(self) -> None:
        captured: dict = {}

        class _FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"id":"msg_1"}'

        def fake_urlopen(req, timeout=30):
            captured["req"] = req
            return _FakeResponse()

        env = {
            "STORY_VOICE_MAIL_MODE": "resend",
            "RESEND_API_KEY": "re_test_key",
            "STORY_VOICE_MAIL_FROM": "Story Voice <noreply@example.com>",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("urllib.request.urlopen", fake_urlopen):
                auth_email.send_verification_email("user@example.com", "123456")

        req = captured.get("req")
        self.assertIsNotNone(req)
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers.get("user-agent"), auth_email.RESEND_USER_AGENT)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ResendRequestHeadersTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("OK: auth email tests")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
