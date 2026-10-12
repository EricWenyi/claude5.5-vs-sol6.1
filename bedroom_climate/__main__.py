"""python -m bedroom_climate: collect Govee H5075 readings and serve the dashboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading

from .server import Api, Settings, make_server
from .store import Store

log = logging.getLogger("bedroom_climate")


def _range(text: str) -> tuple[float, float]:
    try:
        lo, hi = (float(x) for x in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected LOW,HIGH, e.g. 18,22") from None
    if lo >= hi:
        raise argparse.ArgumentTypeError("LOW must be below HIGH")
    return lo, hi


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m bedroom_climate", description=__doc__)
    p.add_argument("--scan", action="store_true", help="list nearby Govee H5075 sensors and exit")
    p.add_argument("--demo", action="store_true", help="serve simulated data; no Bluetooth needed")
    p.add_argument("--device", help="sensor address or name (see --scan); default: first H5075 heard")
    p.add_argument("--db", default="climate.db", help="SQLite file (default: %(default)s)")
    p.add_argument("--host", default="0.0.0.0", help="address to serve on (default: %(default)s, i.e. the whole LAN)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--interval", type=int, default=60, help="seconds between stored samples (default: %(default)s)")
    p.add_argument("--temp-offset", type=float, default=0.0, help="°C added to every temperature reading")
    p.add_argument("--humidity-offset", type=float, default=0.0, help="%%RH added to every humidity reading")
    p.add_argument("--temp-range", type=_range, default=(15.56, 19.44), metavar="LOW,HIGH",
                   help="comfortable sleeping temperature in °C (default: 15.56,19.44 = 60-67 °F)")
    p.add_argument("--humidity-range", type=_range, default=(30.0, 50.0), metavar="LOW,HIGH",
                   help="comfortable humidity in %%RH (default: 30,50)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.scan:
        from .collector import scan

        asyncio.run(scan())
        return

    if args.demo:
        from .demo import DemoCollector

        store = Store(":memory:")
        collector = DemoCollector(store)
    else:
        from .collector import GoveeCollector

        store = Store(args.db)
        collector = GoveeCollector(store, device=args.device, interval_s=args.interval)

    settings = Settings(
        temp_offset=args.temp_offset,
        humidity_offset=args.humidity_offset,
        temp_range_c=args.temp_range,
        humidity_range=args.humidity_range,
        demo=args.demo,
    )
    server = make_server(Api(store, collector, settings), args.host, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Dashboard: http://%s:%d/", "localhost" if args.host == "0.0.0.0" else args.host, args.port)

    try:
        asyncio.run(collector.run())
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("Bluetooth scanning failed. Is Bluetooth on? (Try --demo to see the dashboard without it.)")
        sys.exit(1)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
