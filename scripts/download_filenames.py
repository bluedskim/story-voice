"""Download filenames and Content-Disposition for story audio."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
_INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_title_for_filename(title: str) -> str:
    cleaned = _INVALID_CHARS_RE.sub("", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "동화"


def kst_timestamp(when: datetime | None = None) -> str:
    dt = when or datetime.now(KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    else:
        dt = dt.astimezone(KST)
    return dt.strftime("%Y%m%d-%H%M%S")


def download_basename(title: str, when: datetime | None = None) -> str:
    return f"{sanitize_title_for_filename(title)}_{kst_timestamp(when)}.m4a"


def ascii_fallback_filename(story_id: str, when: datetime | None = None) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", story_id) or "story"
    return f"{safe_id}_{kst_timestamp(when)}.m4a"


def content_disposition_attachment(utf8_filename: str, ascii_filename: str) -> str:
    ascii_safe = ascii_filename.replace("\\", "_").replace('"', "_")
    encoded = quote(utf8_filename, safe="")
    return f"attachment; filename=\"{ascii_safe}\"; filename*=UTF-8''{encoded}"
