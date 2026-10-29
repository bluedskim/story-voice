"""Normalize signup acquisition channel values (utm_source / ref)."""

from __future__ import annotations

SIGNUP_SOURCE_MAX_LEN = 64


def resolve_signup_source_param(
    utm_source: str | None,
    ref: str | None,
) -> str | None:
    """Pick raw query value: utm_source wins over ref."""
    if utm_source is not None and str(utm_source).strip():
        return str(utm_source)
    if ref is not None and str(ref).strip():
        return str(ref)
    return None


def normalize_signup_source(raw: object) -> str | None:
    """Trim, lowercase, keep [a-z0-9_-] only, truncate; invalid → None."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if not s:
        return None
    filtered = "".join(ch for ch in s if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "_-")
    if not filtered:
        return None
    return filtered[:SIGNUP_SOURCE_MAX_LEN]
