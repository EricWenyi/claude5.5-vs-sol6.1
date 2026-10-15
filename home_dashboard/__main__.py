"""python -m home_dashboard: collect the bedroom climate and weigh-ins, and serve the home dashboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading

from .modules.climate import ClimateModule
from .modules.climate.api import Api, Settings
from .modules.climate.store import Store
from .server import make_server

log = logging.getLogger("home_dashboard")


def _range(text: str) -> tuple[float, float]:
    try:
        lo, hi = (float(x) for x in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected LOW,HIGH, e.g. 18,22") from None
    if lo >= hi:
        raise argparse.ArgumentTypeError("LOW must be below HIGH")
    return lo, hi


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m home_dashboard", description=__doc__)
    p.add_argument("--scan", action="store_true", help="list nearby Govee H5075 sensors and exit")
    p.add_argument("--scan-scale", action="store_true", help="list nearby Etekcity scales and exit")
    p.add_argument("--scan-seconds", type=float, default=15, help="how long --scan listens (default: %(default)s)")
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
    w = p.add_argument_group("体重 tab (shown when --scale is given)")
    w.add_argument("--scale", metavar="ADDRESS", help="Etekcity ESF-551 Bluetooth address (see --scan-scale)")
    w.add_argument("--height-cm", type=float, help="your height, for BMI and body fat")
    w.add_argument("--age", type=int, help="your age in years, for body fat")
    w.add_argument("--sex", choices=("male", "female"), help="for body fat")
    w.add_argument("--body-fat-offset", type=float, default=0.0, metavar="POINTS",
                   help="percentage points added to the scale's body-fat estimate, e.g. to match a DEXA scan")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.scan or args.scan_scale:
        if args.scan:
            from .modules.climate.collector import scan
        else:
            from .modules.weight.collector import scan
        asyncio.run(scan(args.scan_seconds))
        return

    modules = [_climate(args)]
    if args.scale or args.demo:
        modules.append(_weight(args))

    server = make_server(modules, args.host, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Dashboard: http://%s:%d/", "localhost" if args.host == "0.0.0.0" else args.host, args.port)

    try:
        asyncio.run(_run(modules))
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("Bluetooth scanning failed. Is Bluetooth on? (Try --demo to see the dashboard without it.)")
        sys.exit(1)
    finally:
        server.shutdown()


def _climate(args) -> ClimateModule:
    if args.demo:
        from .modules.climate.demo import DemoCollector

        store = Store(":memory:")
        collector = DemoCollector(store)
    else:
        from .modules.climate.collector import GoveeCollector

        store = Store(args.db)
        collector = GoveeCollector(store, device=args.device, interval_s=args.interval)
    settings = Settings(
        temp_offset=args.temp_offset,
        humidity_offset=args.humidity_offset,
        temp_range_c=args.temp_range,
        humidity_range=args.humidity_range,
        demo=args.demo,
    )
    return ClimateModule(Api(store, collector, settings), collector)


def _weight(args):
    from .modules.weight import WeightModule
    from .modules.weight.api import Profile, WeightApi
    from .modules.weight.store import WeightStore

    profile = Profile(height_cm=args.height_cm, age=args.age, sex=args.sex, body_fat_offset=args.body_fat_offset)
    if args.demo:
        from .modules.weight.demo import DEMO_PROFILE, add_demo_weigh_ins

        store = WeightStore(":memory:")
        add_demo_weigh_ins(store)
        return WeightModule(WeightApi(store, profile if profile.complete else DEMO_PROFILE), collector=None)

    from .modules.weight.collector import ScaleCollector

    if not profile.complete:
        log.info("Body fat needs --height-cm, --age and --sex; showing weight%s only",
                 " and BMI" if profile.height_cm else "")
    store = WeightStore(args.db)
    return WeightModule(WeightApi(store, profile), ScaleCollector(store, args.scale))


async def _run(modules) -> None:
    await asyncio.gather(*(m.run() for m in modules))


if __name__ == "__main__":
    main()
