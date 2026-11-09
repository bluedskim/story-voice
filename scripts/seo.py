"""robots.txt, sitemap, and public-site URL helpers for SEO."""

from __future__ import annotations

import os
import re
from html import escape

DEFAULT_PUBLIC_URL = "https://story-voice.baem.app"

# Paths that must not be crawled (private APIs and downloadable audio).
ROBOTS_DISALLOW_PREFIXES: tuple[str, ...] = (
    "/api/",
    "/audio/",
)

# HTML documents exposed without login.
SITEMAP_PUBLIC_PATHS: tuple[str, ...] = ("/",)

_ORIGIN_PLACEHOLDER = "%%STORY_VOICE_PUBLIC_ORIGIN%%"


def public_site_url() -> str:
    raw = os.environ.get("STORY_VOICE_PUBLIC_URL", "").strip()
    if raw:
        return raw.rstrip("/")
    return DEFAULT_PUBLIC_URL


def robots_txt_body() -> str:
    base = public_site_url()
    lines = ["User-agent: *", "Allow: /"]
    for prefix in ROBOTS_DISALLOW_PREFIXES:
        lines.append(f"Disallow: {prefix}")
    lines.append("")
    lines.append(f"Sitemap: {base}/sitemap.xml")
    return "\n".join(lines) + "\n"


def sitemap_xml_body() -> str:
    base = public_site_url()
    locs: list[str] = []
    for path in SITEMAP_PUBLIC_PATHS:
        loc = base if path == "/" else f"{base}{path}"
        locs.append(loc)
    urls = "\n".join(f"  <url><loc>{escape(loc)}</loc></url>" for loc in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )


def inject_public_origin(html: str, origin: str | None = None) -> str:
    base = origin or public_site_url()
    return html.replace(_ORIGIN_PLACEHOLDER, base)


def parse_json_ld_blocks(html: str) -> list[str]:
    pattern = re.compile(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    return [m.group(1).strip() for m in pattern.finditer(html)]
