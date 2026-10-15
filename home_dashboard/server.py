"""Tiny HTTP server: the dashboard pages plus each module's JSON API under /api/<module>/."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
_STATIC_FILE = re.compile(r"/([a-z0-9-]+\.(html|js|css))")
_CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Request:
    match: re.Match
    query: dict[str, list[str]]
    body: Callable[[], dict]  # parses the JSON request body when called

    def float_param(self, name: str, default: float) -> float:
        values = self.query.get(name)
        if not values:
            return default
        try:
            return float(values[0])
        except ValueError:
            raise ApiError(400, f"{name} 需是数字") from None


# (HTTP method, path pattern below /api/<module>, handler)
Route = tuple[str, str, Callable[[Request], object]]


class Module(Protocol):
    """One tab of the dashboard: its name in URLs, its tab title, and its API."""

    name: str
    title: str

    def routes(self) -> list[Route]: ...


def make_server(modules: list[Module], host: str, port: int) -> ThreadingHTTPServer:
    routes = [
        (method, re.compile(f"/api/{m.name}{pattern}"), handler)
        for m in modules
        for method, pattern, handler in m.routes()
    ]
    home = {"tabs": [{"id": m.name, "title": m.title} for m in modules]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._file("index.html")
            elif m := _STATIC_FILE.fullmatch(path):
                self._file(m.group(1))
            elif path == "/api/home":
                self._json(200, home)
            else:
                self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_DELETE(self):
            self._route("DELETE")

        def _route(self, method: str):
            url = urlparse(self.path)
            for route_method, pattern, handler in routes:
                if route_method == method and (m := pattern.fullmatch(url.path)):
                    request = Request(m, parse_qs(url.query), self._json_body)
                    try:
                        self._json(200, handler(request))
                    except ApiError as e:
                        self._json(e.status, {"error": str(e)})
                    return
            self._json(404, {"error": "not found"})

        def _file(self, name: str):
            path = STATIC / name
            if not path.is_file():
                self._json(404, {"error": "not found"})
                return
            self._send(200, path.read_bytes(), _CONTENT_TYPES[path.suffix[1:]])

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 10_000:
                raise ApiError(400, "请求体为空或过大")
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                raise ApiError(400, "请求体不是合法 JSON") from None
            if not isinstance(body, dict):
                raise ApiError(400, "请求体需是 JSON 对象")
            return body

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

    return ThreadingHTTPServer((host, port), Handler)
