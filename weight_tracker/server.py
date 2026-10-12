"""Tiny HTTP server: the dashboard page plus a JSON API."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import csvio, stats
from .store import UNITS, Entry, Store, validate

log = logging.getLogger(__name__)

INDEX_HTML = Path(__file__).parent / "static" / "index.html"

MAX_JSON_BYTES = 10_000
MAX_CSV_BYTES = 5_000_000


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, store: Store, demo: bool = False):
        self.store = store
        self.demo = demo

    def config(self) -> dict:
        return {"demo": self.demo}

    def entries(self) -> dict:
        return {"entries": [e.to_json() for e in reversed(self.store.entries())]}

    def summary(self) -> dict:
        return stats.summary(self.store.entries())

    def add_entry(self, body: dict) -> dict:
        try:
            date = dt.date.fromisoformat(str(body["date"]))
            weight = float(body["weight"])
        except (KeyError, TypeError, ValueError):
            raise ApiError(400, "需要填写日期（YYYY-MM-DD）和体重") from None
        time, note = body.get("time") or None, body.get("note") or ""
        if not isinstance(note, str) or not (time is None or isinstance(time, str)):
            raise ApiError(400, "时间和备注需是文字")
        entry = Entry(date, weight, str(body.get("unit", "")), time, note.strip())
        try:
            validate(entry)
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        return {"id": self.store.add(entry)}

    def delete_entry(self, entry_id: int) -> dict:
        if not self.store.delete(entry_id):
            raise ApiError(404, "没有这条记录")
        return {"deleted": entry_id}

    def import_csv(self, text: str, unit: str) -> dict:
        if unit not in UNITS:
            raise ApiError(400, "unit 只能是 lb 或 kg")
        result = csvio.parse(text, default_unit=unit)
        added, duplicates = self.store.add_many(result.entries)
        return {
            "added": added,
            "duplicates": duplicates,
            "errors": result.errors,
            "error_count": result.error_count,
        }

    def export_csv(self) -> str:
        return csvio.dump(self.store.entries())


def make_server(api: Api, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/export.csv":
                name = f"weight-{dt.date.today().isoformat()}.csv"
                self._send(200, api.export_csv().encode(), "text/csv; charset=utf-8",
                           {"Content-Disposition": f'attachment; filename="{name}"'})
            else:
                routes = {"/api/config": api.config, "/api/entries": api.entries, "/api/summary": api.summary}
                self._dispatch(routes.get(path))

        def do_POST(self):
            url = urlparse(self.path)
            if url.path == "/api/entries":
                self._dispatch(lambda: api.add_entry(self._json_body()))
            elif url.path == "/api/import":
                unit = (parse_qs(url.query).get("unit") or ["lb"])[0]
                self._dispatch(lambda: api.import_csv(self._text_body(MAX_CSV_BYTES), unit))
            else:
                self._dispatch(None)

        def do_DELETE(self):
            m = re.fullmatch(r"/api/entries/(\d+)", urlparse(self.path).path)
            self._dispatch(m and (lambda: api.delete_entry(int(m.group(1)))))

        def _dispatch(self, handler):
            if handler is None:
                self._json(404, {"error": "not found"})
                return
            try:
                self._json(200, handler())
            except ApiError as e:
                self._json(e.status, {"error": str(e)})

        def _text_body(self, limit: int) -> str:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= limit:
                raise ApiError(400 if length <= limit else 413, "内容为空或文件过大")
            data = self.rfile.read(length)
            # Excel on a Chinese-language Windows saves plain "CSV" as GBK rather than UTF-8.
            for encoding in ("utf-8", "gb18030"):
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    continue
            raise ApiError(400, "看不懂文件的编码。用 Excel 的话请另存为“CSV UTF-8”")

        def _json_body(self) -> dict:
            try:
                body = json.loads(self._text_body(MAX_JSON_BYTES))
            except ValueError:
                raise ApiError(400, "请求体不是合法 JSON") from None
            if not isinstance(body, dict):
                raise ApiError(400, "请求体需是 JSON 对象")
            return body

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

    return ThreadingHTTPServer((host, port), Handler)
