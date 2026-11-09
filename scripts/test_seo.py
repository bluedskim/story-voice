#!/usr/bin/env python3
"""SEO: robots.txt, sitemap, meta tags, JSON-LD, unauthenticated static routes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from seo import (  # noqa: E402
    ROBOTS_DISALLOW_PREFIXES,
    SITEMAP_PUBLIC_PATHS,
    inject_public_origin,
    parse_json_ld_blocks,
    public_site_url,
    robots_txt_body,
    sitemap_xml_body,
)
from test_auth_helpers import test_server_env  # noqa: E402

INDEX_RAW = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
SEO_PORT = 18766


def http_get(path: str, port: int = SEO_PORT) -> tuple[int, bytes]:
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        res = urllib.request.urlopen(req, timeout=30)
        return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_server(port: int, timeout: float = 12.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            http_get("/api/config", port)
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def served_index_html(port: int) -> str:
    status, raw = http_get("/", port)
    assert status == 200, raw[:200]
    return raw.decode("utf-8")


def test_public_url_env_override() -> None:
    old = os.environ.get("STORY_VOICE_PUBLIC_URL")
    try:
        os.environ["STORY_VOICE_PUBLIC_URL"] = "https://example.test/"
        assert public_site_url() == "https://example.test"
    finally:
        if old is None:
            os.environ.pop("STORY_VOICE_PUBLIC_URL", None)
        else:
            os.environ["STORY_VOICE_PUBLIC_URL"] = old


def test_robots_disallow_and_sitemap_line() -> None:
    body = robots_txt_body()
    assert "User-agent: *" in body
    assert "Allow: /" in body
    for prefix in ROBOTS_DISALLOW_PREFIXES:
        assert f"Disallow: {prefix}" in body
    base = public_site_url()
    assert f"Sitemap: {base}/sitemap.xml" in body


def test_sitemap_lists_only_public_urls() -> None:
    xml = sitemap_xml_body()
    base = public_site_url()
    assert xml.count("<url>") == len(SITEMAP_PUBLIC_PATHS)
    for path in SITEMAP_PUBLIC_PATHS:
        loc = base if path == "/" else f"{base}{path}"
        assert loc in xml
    assert "/api/" not in xml
    assert "/audio/" not in xml
    assert "index.html" not in xml


def test_index_meta_og_twitter_present() -> None:
    html = inject_public_origin(INDEX_RAW, "https://example.test")
    assert '<meta name="description" content=' in html
    assert 'rel="canonical"' in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'property="og:url"' in html
    assert 'property="og:image"' in html
    assert 'name="twitter:card"' in html
    assert 'name="twitter:title"' in html
    assert 'name="twitter:description"' in html


def test_noscript_h1_present() -> None:
    m = re.search(r"<noscript>\s*<h1>(.*?)</h1>", INDEX_RAW, re.S | re.I)
    assert m, "noscript h1 missing"
    assert m.group(1).strip() == "story-voice"


def test_json_ld_parses_as_valid_json() -> None:
    html = inject_public_origin(INDEX_RAW, "https://example.test")
    blocks = parse_json_ld_blocks(html)
    assert blocks, "expected JSON-LD block"
    for block in blocks:
        data = json.loads(block)
        assert data["@type"] == "WebApplication"
        assert data["name"] == "story-voice"
        assert data["url"].startswith("https://")


def test_seo_routes_200_without_auth() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db = tmp_path / "auth.db"
        mail_file = tmp_path / "mail.jsonl"
        env = test_server_env(db, mail_file)
        env["STORY_VOICE_PUBLIC_URL"] = "http://127.0.0.1:18766"
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve.py"), "--host", "127.0.0.1", "--port", str(SEO_PORT)],
            cwd=ROOT,
            env=env,
        )
        try:
            wait_server(SEO_PORT)
            for path in ("/robots.txt", "/sitemap.xml", "/favicon.ico"):
                status, body = http_get(path, SEO_PORT)
                assert status == 200, (path, status, body[:120])
                assert body, path
            html = served_index_html(SEO_PORT)
            assert "%%STORY_VOICE_PUBLIC_ORIGIN%%" not in html
            assert parse_json_ld_blocks(html)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    test_public_url_env_override()
    test_robots_disallow_and_sitemap_line()
    test_sitemap_lists_only_public_urls()
    test_index_meta_og_twitter_present()
    test_noscript_h1_present()
    test_json_ld_parses_as_valid_json()
    test_seo_routes_200_without_auth()
    print("OK: SEO tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
