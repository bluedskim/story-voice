#!/usr/bin/env python3
"""Unit tests for Resend verification email HTTP client."""

from __future__ import annotations

import os
import ssl
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import auth_email  # noqa: E402
import resend_tls  # noqa: E402


class ResendTlsContextTest(unittest.TestCase):
    def setUp(self) -> None:
        resend_tls.clear_resend_ssl_context_cache()

    def tearDown(self) -> None:
        resend_tls.clear_resend_ssl_context_cache()

    def test_filtered_context_excludes_denylisted_roots(self) -> None:
        ctx = resend_tls.get_resend_ssl_context()
        subjects = [str(c.get("subject", ())) for c in ctx.get_ca_certs()]
        self.assertGreater(len(subjects), resend_tls._MIN_TRUST_ANCHORS)
        for subject in subjects:
            self.assertNotRegex(subject, r"emSign", msg=subject)
            self.assertNotIn("AAA Certificate Services", subject)

    def test_filter_removes_emSign_pem_block(self) -> None:
        bundle = resend_tls.load_default_ca_bundle_pem()
        before = len(resend_tls._PEM_CERT_RE.findall(bundle.encode("ascii", errors="surrogateescape")))
        filtered = resend_tls.filter_pem_ca_bundle(bundle)
        after = len(resend_tls._PEM_CERT_RE.findall(filtered.encode("ascii", errors="surrogateescape")))
        self.assertLess(after, before)
        ctx = resend_tls.build_resend_ssl_context(ca_bundle_pem=filtered)
        for cert in ctx.get_ca_certs():
            self.assertFalse(resend_tls.subject_matches_denylist(cert.get("subject", ())))

    def test_custom_denylisted_anchor_not_in_context(self) -> None:
        # Build a real self-signed cert with emSign in the subject via openssl if available.
        import shutil
        import subprocess
        import tempfile

        if not shutil.which("openssl"):
            self.skipTest("openssl not available")
        with tempfile.TemporaryDirectory() as tmp:
            key = os.path.join(tmp, "key.pem")
            cert = os.path.join(tmp, "cert.pem")
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    key,
                    "-out",
                    cert,
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=emSign Test Root CA G3",
                ],
                check=True,
                capture_output=True,
            )
            bad_pem = Path(cert).read_text(encoding="ascii")
        bundle = resend_tls.load_default_ca_bundle_pem() + "\n" + bad_pem
        filtered = resend_tls.filter_pem_ca_bundle(bundle)
        self.assertNotIn("emSign Test Root CA G3", filtered)
        ctx = resend_tls.build_resend_ssl_context(ca_bundle_pem=filtered)
        for info in ctx.get_ca_certs():
            subject = str(info.get("subject", ()))
            self.assertNotIn("emSign Test Root CA G3", subject)

    def test_fail_closed_when_bundle_too_small(self) -> None:
        bundle = resend_tls.load_default_ca_bundle_pem()
        blocks = resend_tls._PEM_CERT_RE.findall(
            bundle.encode("ascii", errors="surrogateescape")
        )
        self.assertGreaterEqual(len(blocks), 2)
        one_cert = blocks[0].decode("ascii", errors="surrogateescape")
        with self.assertRaises(resend_tls.ResendTlsError):
            resend_tls.build_resend_ssl_context(ca_bundle_pem=one_cert)


class ResendLiveTlsTest(unittest.TestCase):
    def setUp(self) -> None:
        resend_tls.clear_resend_ssl_context_cache()

    def test_live_handshake_to_resend_api(self) -> None:
        if os.environ.get("STORY_VOICE_LIVE_TLS", "").strip() != "1":
            self.skipTest("set STORY_VOICE_LIVE_TLS=1 for live Resend TLS check")
        ctx = resend_tls.get_resend_ssl_context()
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=b"{}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(req, timeout=30, context=ctx)
        self.assertIn(raised.exception.code, (401, 403, 422))


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

        def fake_urlopen(req, timeout=30, context=None):
            captured["req"] = req
            captured["context"] = context
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
        ctx = captured.get("context")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers.get("user-agent"), auth_email.RESEND_USER_AGENT)

    def test_send_fails_closed_when_tls_setup_fails(self) -> None:
        env = {
            "STORY_VOICE_MAIL_MODE": "resend",
            "RESEND_API_KEY": "re_test_key",
            "STORY_VOICE_MAIL_FROM": "Story Voice <noreply@example.com>",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch(
                "auth_email.get_resend_ssl_context",
                side_effect=resend_tls.ResendTlsError("broken"),
            ):
                with self.assertRaises(auth_email.EmailSendError) as exc:
                    auth_email.send_verification_email("user@example.com", "123456")
        self.assertEqual(str(exc.exception), "resend_tls_setup")


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ResendTlsContextTest))
    suite.addTests(loader.loadTestsFromTestCase(ResendLiveTlsTest))
    suite.addTests(loader.loadTestsFromTestCase(ResendRequestHeadersTest))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("OK: auth email tests")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
