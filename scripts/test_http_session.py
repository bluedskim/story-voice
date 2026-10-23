"""Cookie + CSRF aware HTTP client for integration tests."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from typing import Any

_SET_COOKIE_RE = re.compile(r"^Set-Cookie:\s*(.+)$", re.I)


class HttpSession:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookies: dict[str, str] = {}
        self.csrf = ""

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _apply_set_cookie(self, headers: Any) -> None:
        if hasattr(headers, "get_all"):
            raw_list = headers.get_all("Set-Cookie") or []
        else:
            raw = headers.get("Set-Cookie")
            raw_list = [raw] if raw else []
        for item in raw_list:
            c = SimpleCookie()
            c.load(item)
            for key in c:
                self.cookies[key] = c[key].value

    def request(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        headers: dict | None = None,
    ) -> urllib.response.addinfourl:
        url = f"{self.base}{path}"
        hdrs = dict(headers or {})
        if self.cookies:
            hdrs["Cookie"] = self._cookie_header()
        if method.upper() != "GET" and self.csrf:
            hdrs["X-CSRF-Token"] = self.csrf
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            res = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            self._apply_set_cookie(exc.headers)
            raise
        self._apply_set_cookie(res.headers)
        return res

    def fetch_config(self) -> dict:
        res = self.request("GET", "/api/config")
        data = json.loads(res.read().decode())
        self.csrf = data.get("csrfToken") or self.cookies.get("sv_csrf", "")
        return data

    def post_json(self, path: str, payload: dict) -> tuple[int, dict | None, bytes]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            res = self.request(
                "POST",
                path,
                data=body,
                headers={"Content-Type": "application/json"},
            )
            raw = res.read()
            if res.status == 204 or not raw:
                return res.status, None, raw
            return res.status, json.loads(raw.decode()), raw
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw.decode()), raw
            except json.JSONDecodeError:
                return exc.code, None, raw
