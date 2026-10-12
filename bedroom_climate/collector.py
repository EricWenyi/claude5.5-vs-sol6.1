"""Listen for Govee H5075 broadcasts over Bluetooth and record them."""

from __future__ import annotations

import asyncio
import logging
import time

from .govee import GOVEE_COMPANY_ID, decode_h5075
from .store import Sample, Store

log = logging.getLogger(__name__)

# A sample older than this is not written again: the sensor is out of range or its battery is dead.
STALE_AFTER_S = 300


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

        async with BleakScanner(detection_callback=self.on_advertisement):
            log.info("Scanning for Govee H5075 broadcasts...")
            while True:
                await asyncio.sleep(self.interval_s)
                s = self.latest
                if s is None:
                    log.warning("No H5075 heard yet. Is the sensor within Bluetooth range?")
                elif time.time() - s.ts < STALE_AFTER_S:
                    self.store.add_reading(s)
                else:
                    log.warning("Last broadcast from %s was %d s ago", s.device, time.time() - s.ts)


async def scan(seconds: float = 15) -> None:
    """Print every Govee H5072/H5075 in range, to find the right --device value."""
    from bleak import BleakScanner

    found: dict[str, str] = {}

    def on_adv(device, adv):
        payload = adv.manufacturer_data.get(GOVEE_COMPANY_ID)
        reading = decode_h5075(payload) if payload else None
        if reading:
            found[device.address] = (
                f"{adv.local_name or device.name or '?':<16} {device.address:<40} "
                f"{reading.temp_c:5.1f}°C {reading.humidity:5.1f}%  battery {reading.battery}%  {adv.rssi} dBm"
            )

    print(f"Listening for {seconds:.0f} s...")
    async with BleakScanner(detection_callback=on_adv):
        await asyncio.sleep(seconds)
    if not found:
        print("No Govee H5075 found. Check the batteries and move closer to this computer.")
    for line in found.values():
        print(line)
