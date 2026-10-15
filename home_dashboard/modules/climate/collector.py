"""Listen for Govee H5075 broadcasts over Bluetooth and record them."""

from __future__ import annotations

import asyncio
import logging
import time

from ...ble import allow_duplicates
from .govee import GOVEE_COMPANY_ID, decode_h5075
from .store import Sample, Store

log = logging.getLogger(__name__)

# A sample older than this is not written again: the sensor is out of range or its battery is dead.
STALE_AFTER_S = 300
# Restart the scan when nothing new has arrived for this long. Unless the app asks for duplicates
# (bleak doesn't; see ble.allow_duplicates), macOS CoreBluetooth reports a device once per scan and
# then only when its broadcast changes, so while the room stays at the same temperature a Mac
# hears nothing. A fresh scan reports the sensor again.
RESCAN_AFTER_S = 20


class GoveeCollector:
    """Keeps the newest broadcast in memory and writes it to the store once per interval.

    The sensor broadcasts every couple of seconds; one row per minute is plenty for a dashboard.
    """

    def __init__(self, store: Store, device: str | None = None, interval_s: int = 60):
        self.store = store
        self.interval_s = interval_s
        self._wanted = device.upper() if device else None
        self._locked_address: str | None = None
        self.latest: Sample | None = None
        self._heard_at = 0.0  # time.monotonic() of the newest matching broadcast
        self._stored: Sample | None = None
        self.heard = 0  # matching broadcasts since the last stored sample (diagnostics)
        self.rescans = 0

    def _matches(self, address: str, name: str) -> bool:
        if self._wanted:
            # Exact address, or part of the name ("1A2B" matches "GVH5075_1A2B").
            return self._wanted == address.upper() or (bool(name) and self._wanted in name.upper())
        # No device given: stick with the first H5075 we hear, so a neighbour's sensor can't mix in.
        if self._locked_address is None:
            self._locked_address = address
            log.info("Using %s (%s). Pass --device to pick a different sensor.", name or "?", address)
        return address == self._locked_address

    def on_advertisement(self, device, adv) -> None:
        payload = adv.manufacturer_data.get(GOVEE_COMPANY_ID)
        reading = decode_h5075(payload) if payload else None
        if reading is None:
            return
        name = adv.local_name or device.name or ""
        if not self._matches(device.address, name):
            return
        log.debug("%s %s raw=%s rssi=%s", name, device.address, payload.hex(), adv.rssi)
        self.heard += 1
        self._heard_at = time.monotonic()
        self.latest = Sample(
            ts=time.time(),
            device=name or device.address,
            temp_c=reading.temp_c,
            humidity=reading.humidity,
            battery=reading.battery,
            rssi=adv.rssi,
        )

    async def run(self) -> None:
        from bleak import BleakScanner  # imported here so --demo works without Bluetooth

        # One scanner for the whole run: every BleakScanner on macOS creates its own CBCentralManager.
        scanner = BleakScanner(detection_callback=self.on_advertisement)
        log.info("Scanning for Govee H5075 broadcasts...")
        next_store = time.monotonic() + self.interval_s
        while True:
            await scanner.start()
            allow_duplicates(scanner)
            started = time.monotonic()
            try:
                while time.monotonic() - max(started, self._heard_at) < RESCAN_AFTER_S:
                    await asyncio.sleep(1)
                    now = time.monotonic()
                    if now >= next_store:
                        next_store = max(next_store + self.interval_s, now)  # no burst after a stall
                        self._store_latest()
            finally:
                await scanner.stop()
            self.rescans += 1

    def _store_latest(self) -> None:
        s = self.latest
        heard, rescans = self.heard, self.rescans
        self.heard = self.rescans = 0
        if s is None:
            log.warning("No H5075 heard yet. Is the sensor within Bluetooth range?")
        elif time.time() - s.ts >= STALE_AFTER_S:
            log.warning("Last broadcast from %s was %d s ago", s.device, time.time() - s.ts)
        elif s is self._stored:
            log.warning("No new broadcast from %s in the last %d s (%d rescans); nothing saved",
                        s.device, self.interval_s, rescans)
        else:
            self.store.add_reading(s)
            self._stored = s
            log.info("Saved %.1f°C %.1f%% battery %s%% rssi %s, %d s old (%d broadcasts, %d rescans)",
                     s.temp_c, s.humidity, s.battery, s.rssi, time.time() - s.ts, heard, rescans)


async def scan(seconds: float = 15) -> None:
    """Print every Govee H5072/H5075 in range, to find the right --device value."""
    from bleak import BleakScanner

    found: dict[str, str] = {}
    counts: dict[str, int] = {}
    seen: dict[str, str] = {}  # every advertiser, to tell "no permission/radio" from "sensor not in range"
    other_govee: dict[str, str] = {}

    def on_adv(device, adv):
        name = adv.local_name or device.name or ""
        seen[device.address] = name
        if GOVEE_COMPANY_ID in adv.manufacturer_data or name.upper().startswith(("GV", "GOVEE", "IHOMENT")):
            other_govee[device.address] = (
                f"{name or '?'} {device.address} {adv.rssi} dBm "
                + " ".join(f"{k:#06x}={v.hex()}" for k, v in adv.manufacturer_data.items())
            )
        payload = adv.manufacturer_data.get(GOVEE_COMPANY_ID)
        reading = decode_h5075(payload) if payload else None
        if reading:
            counts[device.address] = counts.get(device.address, 0) + 1
            found[device.address] = (
                f"{adv.local_name or device.name or '?':<16} {device.address:<40} "
                f"{reading.temp_c:5.1f}°C {reading.humidity:5.1f}%  battery {reading.battery}%  {adv.rssi} dBm  "
                f"raw {payload.hex()}  ({counts[device.address]} broadcasts)"
            )
            log.debug("%s %s raw=%s rssi=%s", adv.local_name or device.name, device.address, payload.hex(), adv.rssi)

    print(f"Listening for {seconds:.0f} s...")
    async with BleakScanner(detection_callback=on_adv):
        await asyncio.sleep(seconds)
    print(f"Heard {len(seen)} Bluetooth devices in total.")
    if not found:
        print("No Govee H5075 found. Check the batteries and move closer to this computer.")
        for line in other_govee.values():
            print("  Govee-like but not decoded:", line)
    for line in found.values():
        print(line)
