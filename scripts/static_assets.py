"""Content hashes for cache-busted static asset URLs."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"

CACHE_BUST_ASSETS = (
    "styles.css",
    "app.js",
    "auth.js",
    "modal.js",
    "signup-source.js",
    "playback.js",
    "favicon.ico",
    "manifest.webmanifest",
    "icons/favicon.svg",
    "icons/icon-16.png",
    "icons/icon-32.png",
    "icons/icon-48.png",
    "icons/icon-180.png",
    "icons/icon-192.png",
    "icons/icon-512.png",
)


def _short_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:12]


def web_asset_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for rel in CACHE_BUST_ASSETS:
        path = WEB_DIR / rel
        if path.is_file():
            versions[rel] = _short_hash(path)
    return versions


def inject_asset_versions(text: str, versions: dict[str, str]) -> str:
    for rel, ver in sorted(versions.items(), key=lambda x: -len(x[0])):
        text = text.replace(f'href="{rel}"', f'href="{rel}?v={ver}"')
        text = text.replace(f'src="{rel}"', f'src="{rel}?v={ver}"')
        text = text.replace(f'"{rel}"', f'"{rel}?v={ver}"')
    return text


def inject_module_imports(text: str, versions: dict[str, str]) -> str:
    for rel in ("auth.js", "modal.js", "signup-source.js", "playback.js"):
        ver = versions.get(rel)
        if not ver:
            continue
        text = text.replace(f'from "./{rel}"', f'from "./{rel}?v={ver}"')
    return text


def inject_app_js_imports(text: str, versions: dict[str, str]) -> str:
    """Cache-bust relative ES module imports from app.js."""
    return inject_module_imports(text, versions)


def auth_js_served_body(versions: dict[str, str] | None = None) -> bytes:
    versions = versions or web_asset_versions()
    raw = (WEB_DIR / "auth.js").read_text(encoding="utf-8")
    return inject_module_imports(raw, versions).encode("utf-8")


def app_js_served_body(versions: dict[str, str] | None = None) -> bytes:
    versions = versions or web_asset_versions()
    raw = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    return inject_app_js_imports(raw, versions).encode("utf-8")
