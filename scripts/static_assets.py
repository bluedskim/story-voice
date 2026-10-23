"""Content hashes for cache-busted static asset URLs."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"


def _short_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:12]


def web_asset_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("styles.css", "app.js", "auth.js"):
        path = WEB_DIR / name
        if path.is_file():
            versions[name] = _short_hash(path)
    return versions


def inject_asset_versions(html: str, versions: dict[str, str]) -> str:
    for name, ver in versions.items():
        html = html.replace(f'href="{name}"', f'href="{name}?v={ver}"')
        html = html.replace(f'src="{name}"', f'src="{name}?v={ver}"')
    return html
