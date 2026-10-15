"""体重 tab: weigh-ins from an Etekcity ESF-551 scale."""

from __future__ import annotations

from ...server import Route
from .api import WeightApi


class WeightModule:
    name = "weight"
    title = "体重"

    def __init__(self, api: WeightApi, collector):
        self.api = api
        self.collector = collector  # None in --demo mode

    def routes(self) -> list[Route]:
        api = self.api
        return [
            ("GET", "/latest", lambda r: api.latest()),
            ("GET", "/history", lambda r: api.history(r.float_param("days", 90))),
            ("DELETE", r"/readings/(\d+)", lambda r: api.delete(int(r.match.group(1)))),
        ]

    async def run(self) -> None:
        if self.collector is not None:
            await self.collector.run()
