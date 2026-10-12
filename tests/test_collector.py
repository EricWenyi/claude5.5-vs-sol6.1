import asyncio
import logging
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from bedroom_climate import collector
from bedroom_climate.collector import GoveeCollector
from bedroom_climate.store import Store

PAYLOAD = bytes.fromhex("0003519e6400")  # 21.7 °C, 50.2 %, battery 100 %


def advert(address, name, payload):
    return SimpleNamespace(address=address, name=name), SimpleNamespace(
        local_name=name, rssi=-70, manufacturer_data={0xEC88: payload})


class CollectorTest(unittest.TestCase):
    def test_locks_onto_first_sensor(self):
        c = GoveeCollector(Store(":memory:"))
        c.on_advertisement(*advert("AA", "GVH5075_AAAA", bytes.fromhex("0003519e6400")))
        c.on_advertisement(*advert("BB", "GVH5075_BBBB", bytes.fromhex("0080d2285500")))
        self.assertEqual((c.latest.device, c.latest.temp_c), ("GVH5075_AAAA", 21.7))

    def test_device_filter_matches_part_of_name(self):
        c = GoveeCollector(Store(":memory:"), device="bbbb")
        c.on_advertisement(*advert("AA", "GVH5075_AAAA", bytes.fromhex("0003519e6400")))
        self.assertIsNone(c.latest)
        c.on_advertisement(*advert("BB", "GVH5075_BBBB", bytes.fromhex("0080d2285500")))
        self.assertEqual(c.latest.temp_c, -5.3)

    def test_ignores_other_broadcasts(self):
        c = GoveeCollector(Store(":memory:"))
        device, adv = advert("AA", "iPhone", b"")
        adv.manufacturer_data = {0x004C: b"\x02\x15"}
        c.on_advertisement(device, adv)
        self.assertIsNone(c.latest)


class _Stop(Exception):
    pass


class FakeClock:
    """Replaces `time` and `asyncio.sleep` inside collector.py, so simulated minutes pass instantly."""

    def __init__(self, run_for_s):
        self.start = 1_800_000_000.0
        self.now = self.start
        self.end = self.start + run_for_s
        self.on_tick = []

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        if self.now > self.end:
            raise _Stop
        for f in self.on_tick:
            f()


ALLOW_DUPLICATES = "kCBScanOptionAllowDuplicates"  # value of CBCentralManagerScanOptionAllowDuplicatesKey


class FakeBluetooth:
    """BleakScanner stand-in with one H5075 in the room, filtering duplicates like CoreBluetooth.

    A scan reports the sensor once when it starts and then only on `broadcast()`, i.e. when the
    reading changes, unless the scan was asked for duplicates: then every `tick()` reports it too.
    With private_api=False the scanner lacks bleak's CoreBluetooth internals, as on another
    platform or with a bleak version that moved them.
    """

    def __init__(self, in_range=lambda: True, private_api=True):
        self.in_range = in_range
        self.starts = 0
        self.scanning = []
        self.duplicates = False
        bt = self

        class CBCentralManager:
            def scanForPeripheralsWithServices_options_(self, uuids, options):
                bt.duplicates = bool(options and options.get(ALLOW_DUPLICATES))

        class BleakScanner:
            def __init__(self, detection_callback=None, **kwargs):
                self.callback = detection_callback
                if private_api:
                    manager = SimpleNamespace(central_manager=CBCentralManager())
                    self._backend = SimpleNamespace(_manager=manager)

            async def start(self):
                bt.starts += 1
                bt.scanning.append(self)
                bt.duplicates = False  # bleak starts the scan without options
                bt.broadcast()

            async def stop(self):
                bt.scanning.remove(self)

            async def __aenter__(self):
                await self.start()
                return self

            async def __aexit__(self, *exc):
                await self.stop()

        self.modules = {
            "bleak": SimpleNamespace(BleakScanner=BleakScanner),
            "CoreBluetooth": SimpleNamespace(CBCentralManagerScanOptionAllowDuplicatesKey=ALLOW_DUPLICATES),
        }

    def broadcast(self):
        if self.in_range():
            for scanner in self.scanning:
                scanner.callback(*advert("3DAB0DE0", "GVH5075_2186", PAYLOAD))

    def tick(self):
        if self.duplicates:
            self.broadcast()


class CollectorRunTest(unittest.TestCase):
    def run_collector(self, clock, bluetooth):
        """Run GoveeCollector.run() until the clock runs out; return [(store_time, sample), ...]."""
        saved = []
        store = SimpleNamespace(add_reading=lambda s: saved.append((clock.now, s)))
        c = GoveeCollector(store, device="2186", interval_s=60)
        clock.on_tick.append(bluetooth.tick)
        with mock.patch.object(collector, "time", clock), \
             mock.patch.object(collector, "asyncio", SimpleNamespace(sleep=clock.sleep)), \
             mock.patch.dict(sys.modules, bluetooth.modules), \
             self.assertLogs(collector.log, "DEBUG") as logs:
            with self.assertRaises(_Stop):
                asyncio.run(c.run())
        self.warnings = [r for r in logs.records if r.levelno >= logging.WARNING]
        return saved

    def test_asks_macos_for_every_broadcast(self):
        clock, bt = FakeClock(run_for_s=300), FakeBluetooth()
        saved = self.run_collector(clock, bt)
        self.assertEqual(bt.starts, 1)
        self.assertEqual(len({s.ts for _, s in saved}), 5)
        for stored_at, s in saved:
            self.assertLessEqual(stored_at - s.ts, 5)

    def test_restarts_scan_when_macos_stops_reporting(self):
        # Without access to the duplicates option the reading never changes, so after the
        # first report each scan goes quiet.
        clock, bt = FakeClock(run_for_s=300), FakeBluetooth(private_api=False)
        saved = self.run_collector(clock, bt)
        self.assertEqual(len(saved), 5)
        self.assertEqual(len({s.ts for _, s in saved}), 5, "each minute should store a new broadcast")
        for stored_at, s in saved:
            self.assertLessEqual(stored_at - s.ts, 30)

    def test_keeps_scanning_while_broadcasts_arrive(self):
        # Linux, or a Mac while the reading keeps changing: no reason to restart the scan.
        clock, bt = FakeClock(run_for_s=300), FakeBluetooth(private_api=False)
        clock.on_tick.append(bt.broadcast)
        saved = self.run_collector(clock, bt)
        self.assertEqual(bt.starts, 1)
        self.assertEqual(len(saved), 5)

    def test_picks_sensor_up_after_it_was_out_of_range(self):
        clock = FakeClock(run_for_s=240)
        bt = FakeBluetooth(in_range=lambda: clock.now >= clock.start + 90)
        saved = self.run_collector(clock, bt)
        self.assertEqual([round(t - clock.start) for t, _ in saved], [120, 180, 240])

    def test_does_not_store_the_same_broadcast_twice(self):
        # Heard once, then the sensor goes out of range: one row, not one per minute.
        clock = FakeClock(run_for_s=240)
        bt = FakeBluetooth(in_range=lambda: clock.now == clock.start)
        saved = self.run_collector(clock, bt)
        self.assertEqual([round(t - clock.start) for t, _ in saved], [60])
        self.assertEqual(len(self.warnings), 3, "each minute without a new broadcast should be logged")


if __name__ == "__main__":
    unittest.main()
