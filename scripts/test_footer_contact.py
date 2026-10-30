"""Footer contact link: mailto in href only, no raw address/handle in visible text."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def footer_html() -> str:
    m = re.search(r'<footer class="footer">(.*?)</footer>', INDEX, re.S)
    assert m, "footer missing"
    return m.group(1)


def test_footer_has_single_contact_mailto() -> None:
    assert INDEX.count("mailto:") == 1
    m = re.search(r'<a id="contact-link"[^>]*href="mailto:([^"]+)"[^>]*>(.*?)</a>', footer_html(), re.S)
    assert m, "contact link missing from footer"
    assert "@" in m.group(1)
    assert m.group(2).strip() == "문의하기"


def test_contact_address_not_visible_text() -> None:
    no_comments = re.sub(r"<!--.*?-->", "", INDEX, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", no_comments)
    assert "@" not in visible
    assert "bluedskim" not in visible


if __name__ == "__main__":
    test_footer_has_single_contact_mailto()
    test_contact_address_not_visible_text()
    print("ok")
