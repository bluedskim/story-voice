"""TLS trust policy for outbound Resend API calls (CVE-2026-91403 hardening)."""

from __future__ import annotations

import logging
import os
import re
import ssl
from functools import lru_cache

LOG = logging.getLogger("story-voice.auth.email.tls")

# Java trust-store aliases: emsigneccrootcag3, comodoaaaca — distrust by subject.
# Extend this tuple when advisories add roots; patterns match any subject RDN value.
DENYLIST_SUBJECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"emSign", re.IGNORECASE),
    re.compile(r"AAA Certificate Services", re.IGNORECASE),
)

_MIN_TRUST_ANCHORS = 32

_PEM_CERT_RE = re.compile(
    rb"-----BEGIN CERTIFICATE-----\r?\n.*?\r?\n-----END CERTIFICATE-----",
    re.DOTALL,
)


class ResendTlsError(Exception):
    """Resend-specific TLS setup failed; do not fall back to unverified TLS."""


def subject_matches_denylist(subject: tuple) -> bool:
    """Return True if any subject RDN value matches a denylisted pattern."""
    values: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, tuple):
            if len(node) == 2 and isinstance(node[0], str) and isinstance(node[1], str):
                values.append(node[1])
            else:
                for item in node:
                    walk(item)

    walk(subject)
    text = " | ".join(values)
    return any(pattern.search(text) for pattern in DENYLIST_SUBJECT_PATTERNS)


def _pem_cert_subject(pem: str) -> tuple | None:
    scratch = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        scratch.load_verify_locations(cadata=pem)
    except ssl.SSLError:
        return None
    certs = scratch.get_ca_certs()
    if not certs:
        return None
    subject = certs[0].get("subject")
    return subject if isinstance(subject, tuple) else None


def pem_certificate_is_denylisted(pem: str) -> bool:
    subject = _pem_cert_subject(pem)
    if subject is None:
        return False
    return subject_matches_denylist(subject)


def filter_pem_ca_bundle(bundle_pem: str) -> str:
    """Drop PEM trust anchors whose subject matches the denylist."""
    if isinstance(bundle_pem, str):
        raw = bundle_pem.encode("utf-8", errors="surrogateescape")
    else:
        raw = bundle_pem
    kept: list[bytes] = []
    for block in _PEM_CERT_RE.findall(raw):
        pem = block.decode("ascii", errors="surrogateescape")
        if pem_certificate_is_denylisted(pem):
            continue
        kept.append(block)
    if not kept:
        return ""
    return b"\n".join(kept).decode("ascii", errors="surrogateescape") + "\n"


def _read_text_file(path: str) -> str:
    with open(path, encoding="ascii", errors="surrogateescape") as fh:
        return fh.read()


def _read_capath_dir(capath: str) -> str:
    chunks: list[str] = []
    for name in sorted(os.listdir(capath)):
        full = os.path.join(capath, name)
        if os.path.isfile(full):
            chunks.append(_read_text_file(full))
    return "\n".join(chunks)


def load_default_ca_bundle_pem() -> str:
    """Load the same CA bundle create_default_context() would use (certifi if installed)."""
    certifi_path: str | None = None
    try:
        import certifi  # type: ignore[import-not-found]
    except ImportError:
        certifi = None  # type: ignore[misc, assignment]
    if certifi is not None:
        certifi_path = certifi.where()
    if certifi_path and os.path.isfile(certifi_path):
        return _read_text_file(certifi_path)

    paths = ssl.get_default_verify_paths()
    if paths.cafile and os.path.isfile(paths.cafile):
        return _read_text_file(paths.cafile)
    if paths.capath and os.path.isdir(paths.capath):
        bundle = _read_capath_dir(paths.capath)
        if bundle.strip():
            return bundle
    env_file = os.environ.get("SSL_CERT_FILE", "").strip()
    if env_file and os.path.isfile(env_file):
        return _read_text_file(env_file)
    env_dir = os.environ.get("SSL_CERT_DIR", "").strip()
    if env_dir and os.path.isdir(env_dir):
        bundle = _read_capath_dir(env_dir)
        if bundle.strip():
            return bundle
    raise ResendTlsError("ca_bundle_not_found")


def build_resend_ssl_context(*, ca_bundle_pem: str | None = None) -> ssl.SSLContext:
    """Build a client context: hostname verify + filtered public trust anchors only."""
    source = ca_bundle_pem if ca_bundle_pem is not None else load_default_ca_bundle_pem()
    filtered = filter_pem_ca_bundle(source)
    anchor_count = len(_PEM_CERT_RE.findall(filtered.encode("ascii", errors="surrogateescape")))
    if anchor_count < _MIN_TRUST_ANCHORS:
        raise ResendTlsError(
            f"filtered_ca_bundle_too_small anchors={anchor_count} minimum={_MIN_TRUST_ANCHORS}"
        )

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    try:
        ctx.load_verify_locations(cadata=filtered)
    except ssl.SSLError as exc:
        raise ResendTlsError("filtered_ca_bundle_load_failed") from exc
    return ctx


@lru_cache(maxsize=1)
def get_resend_ssl_context() -> ssl.SSLContext:
    ctx = build_resend_ssl_context()
    anchor_count = len(ctx.get_ca_certs())
    LOG.debug("Resend TLS context loaded with %s trust anchors (denylist filtered)", anchor_count)
    return ctx


def clear_resend_ssl_context_cache() -> None:
    get_resend_ssl_context.cache_clear()
