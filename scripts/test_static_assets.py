"""Cache-busting helpers for web assets."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from static_assets import (  # noqa: E402
    app_js_served_body,
    inject_app_js_imports,
    inject_asset_versions,
    web_asset_versions,
)


def test_inject_asset_versions_html() -> None:
    versions = {"styles.css": "abc", "app.js": "def"}
    html = '<link rel="stylesheet" href="styles.css" />\n<script src="app.js" type="module"></script>'
    out = inject_asset_versions(html, versions)
    assert 'href="styles.css?v=abc"' in out
    assert 'src="app.js?v=def"' in out


def test_inject_app_js_imports() -> None:
    versions = web_asset_versions()
    ver = versions.get("auth.js")
    assert ver, "auth.js should be versioned"
    src = 'import { x } from "./auth.js";'
    out = inject_app_js_imports(src, versions)
    assert f'from "./auth.js?v={ver}"' in out


def test_app_js_served_body() -> None:
    body = app_js_served_body().decode("utf-8")
    ver = web_asset_versions().get("auth.js")
    assert ver and f'./auth.js?v={ver}"' in body


def main() -> None:
    test_inject_asset_versions_html()
    test_inject_app_js_imports()
    test_app_js_served_body()
    print("OK: static asset cache-bust tests")


if __name__ == "__main__":
    main()
