#!/usr/bin/env python3
"""Tests for signup acquisition channel normalization."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from signup_source import (  # noqa: E402
    SIGNUP_SOURCE_MAX_LEN,
    normalize_signup_source,
    resolve_signup_source_param,
)


def test_normalize_trims_and_lowercases() -> None:
    assert normalize_signup_source("  Newsletter  ") == "newsletter"


def test_normalize_strips_invalid_chars() -> None:
    assert normalize_signup_source("foo@bar!") == "foobar"
    assert normalize_signup_source("!!!") is None


def test_normalize_truncates() -> None:
    long_val = "a" * (SIGNUP_SOURCE_MAX_LEN + 10)
    out = normalize_signup_source(long_val)
    assert out is not None
    assert len(out) == SIGNUP_SOURCE_MAX_LEN


def test_normalize_rejects_non_string() -> None:
    assert normalize_signup_source(123) is None
    assert normalize_signup_source(None) is None
    assert normalize_signup_source("") is None


def test_precedence_utm_over_ref() -> None:
    assert resolve_signup_source_param("newsletter", "friend") == "newsletter"
    assert resolve_signup_source_param("", "friend") == "friend"
    assert resolve_signup_source_param(None, "friend") == "friend"
    assert resolve_signup_source_param("  ", "friend") == "friend"


def test_precedence_empty_when_missing() -> None:
    assert resolve_signup_source_param(None, None) is None
    assert resolve_signup_source_param("", "") is None


def test_client_first_touch() -> None:
    import subprocess

    script = ROOT / "scripts" / "test_signup_source_client.mjs"
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)


def main() -> None:
    test_normalize_trims_and_lowercases()
    test_normalize_strips_invalid_chars()
    test_normalize_truncates()
    test_normalize_rejects_non_string()
    test_precedence_utm_over_ref()
    test_precedence_empty_when_missing()
    test_client_first_touch()
    print("OK: signup_source unit tests")


if __name__ == "__main__":
    main()
