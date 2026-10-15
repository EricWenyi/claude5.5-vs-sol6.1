"""温湿度 tab: the bedroom's Govee H5075."""

from __future__ import annotations

from ...server import Route
from .api import Api


class ClimateModule:
    name = "climate"
    title = "温湿度"

    def __init__(self, api: Api, collector):
        self.api = api
        self.collector = collector

    def routes(self) -> list[Route]:
        api = self.api
        return [
            ("GET", "/config", lambda r: api.config()),
            ("GET", "/latest", lambda r: api.latest()),
            ("GET", "/history", lambda r: api.history(r.float_param("hours", 24))),
            ("GET", "/checks", lambda r: api.checks()),
            ("POST", "/checks", lambda r: api.add_check(r.body())),
            ("DELETE", r"/checks/(\d+)", lambda r: api.delete_check(int(r.match.group(1)))),
        ]

    async def run(self) -> None:
        await self.collector.run()
