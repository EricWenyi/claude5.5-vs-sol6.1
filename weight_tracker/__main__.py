"""python -m weight_tracker: serve the weight dashboard, import a CSV, or print the averages."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import csvio, stats
from .server import Api, make_server
from .store import Store, from_kg

log = logging.getLogger("weight_tracker")


def report(store: Store, unit: str, weeks: int = 12, months: int = 12) -> None:
    days = stats.daily(store.entries())
    if not days:
        print("还没有任何记录。")
        return

    def num(kg: float | None, signed: bool = False) -> str:
        if kg is None:
            return "–"
        return f"{from_kg(kg, unit):+.1f}" if signed else f"{from_kg(kg, unit):.1f}"

    for title, periods, label, vs in (
        (f"每周平均（{unit}，周一至周日）", stats.weekly(days)[-weeks:], lambda p: f"{p.start:%Y-%m-%d} 起", "比上周"),
        (f"每月平均（{unit}）", stats.monthly(days)[-months:], lambda p: f"{p.start:%Y-%m}", "比上月"),
    ):
        print(title)
        print(f"{'':13}  天数    平均    最低    最高  {vs}")
        for p in reversed(periods):
            print(f"{label(p):13}  {p.days:4}  {num(p.avg):>6}  {num(p.min):>6}  {num(p.max):>6}  {num(p.change, True):>6}")
        print()

    t = stats.trend(days)
    if t:
        print(f"近 4 周趋势：每周 {from_kg(t['kg_per_week'], unit):+.2f} {unit}"
              f"（{t['start']} 至 {t['end']}，{t['days']} 天有记录）")
    else:
        print(f"近 4 周趋势：记录还不够（需要最近 {stats.TREND_DAYS} 天里至少 {stats.TREND_MIN_DAYS} 天、跨度一周以上）")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m weight_tracker", description=__doc__)
    p.add_argument("--demo", action="store_true", help="serve six months of made-up data (nothing is saved)")
    p.add_argument("--db", default="weight.db", help="SQLite file (default: %(default)s)")
    p.add_argument("--host", default="0.0.0.0", help="address to serve on (default: %(default)s, i.e. the whole LAN)")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--import", dest="import_csv", metavar="FILE", help="add the weigh-ins in a CSV file, then exit")
    p.add_argument("--report", action="store_true", help="print weekly/monthly averages and the trend, then exit")
    p.add_argument("--unit", choices=("lb", "kg"), default="lb",
                   help="unit for --report, and for --import when the file doesn't say (default: %(default)s)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.demo:
        from .demo import fill

        store = Store(":memory:")
        fill(store)
    else:
        store = Store(args.db)

    if args.import_csv:
        result = csvio.parse(Path(args.import_csv).read_text(encoding="utf-8-sig"), default_unit=args.unit)
        added, duplicates = store.add_many(result.entries)
        print(f"新增 {added} 条，跳过重复 {duplicates} 条，有问题 {result.error_count} 行。")
        for message in result.errors:
            print("  " + message)
        sys.exit(1 if result.error_count and not added else 0)

    if args.report:
        report(store, args.unit)
        return

    server = make_server(Api(store, demo=args.demo), args.host, args.port)
    log.info("Dashboard: http://%s:%d/", "localhost" if args.host == "0.0.0.0" else args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
