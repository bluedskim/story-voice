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
