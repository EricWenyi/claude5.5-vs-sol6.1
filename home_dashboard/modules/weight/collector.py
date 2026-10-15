"""Record every weigh-in on an Etekcity ESF-551 scale.

The scale is asleep until someone steps on it; it then advertises for a while, we connect
(etekcity_esf551_ble does the protocol), and it notifies the final weight and impedance.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from etekcity_esf551_ble import IMPEDANCE_KEY, WEIGHT_KEY, ScaleData

from ...ble import allow_duplicates
from .store import WeightStore

log = logging.getLogger(__name__)

# The same final reading arriving again this soon is a resend (e.g. after a reconnect), not a new weigh-in.
DUPLICATE_WITHIN_S = 120
# Log "scale woke up" again only after it has been quiet this long.
AWAKE_LOG_GAP_S = 60


class ScaleCollector:
    def __init__(self, store: WeightStore, address: str, clock: Callable[[], float] = time.time):
        self.store = store
        self.address = address.upper()
        self._clock = clock
        self._last: tuple[float, float, int | None] | None = None  # (time, kg, impedance) last stored
        self._seen_at = 0.0

    def on_reading(self, data: ScaleData) -> None:
        kg = data.measurements.get(WEIGHT_KEY)
        if kg is None:
            return
        impedance = data.measurements.get(IMPEDANCE_KEY)
        now = self._clock()
        if self._last and self._last[1:] == (kg, impedance) and now - self._last[0] < DUPLICATE_WITHIN_S:
            log.debug("Ignoring repeated reading %.2f kg", kg)
            return
        self._last = (now, kg, impedance)
        self.store.add(now, kg, impedance)
        log.info("Weighed %.2f kg (impedance %s)", kg, f"{impedance} ohm" if impedance else "not measured")

    def _on_advertisement(self, device, adv) -> None:
        if device.address.upper() != self.address:
            return
        now = self._clock()
        if now - self._seen_at > AWAKE_LOG_GAP_S:
            log.info("Scale woke up (%s dBm)", adv.rssi)
        self._seen_at = now

    async def run(self) -> None:
        from bleak.backends.scanner import get_platform_scanner_backend_type
        from etekcity_esf551_ble import ESF551Scale

        # Our own scanner so duplicates can be switched on: CoreBluetooth would otherwise report
        # the scale once and might stay silent when it wakes up again tomorrow. use_bdaddr: the
        # scale is identified by its MAC address, which macOS hides by default.
        backend_cls, _ = get_platform_scanner_backend_type()
        scanner = backend_cls(None, None, "active", bluez={}, cb={"use_bdaddr": True})
        scanner.register_detection_callback(self._on_advertisement)
        scale = ESF551Scale(self.address, self.on_reading, bleak_scanner_backend=scanner)
        await scale.async_start()
        allow_duplicates(scanner)
        log.info("Waiting for the scale %s", self.address)
        try:
            await asyncio.Event().wait()
        finally:
            await scale.async_stop()


async def scan(seconds: float = 30) -> None:
    """Print every Etekcity scale in range, to find the right --scale value."""
    from bleak import BleakScanner
    from etekcity_esf551_ble import ETEKCITY_MANUFACTURER_ID, detect_model

    found: dict[str, str] = {}

    def on_adv(device, adv):
        name = adv.local_name or device.name or ""
        if ETEKCITY_MANUFACTURER_ID in adv.manufacturer_data or "etekcity" in name.lower():
            model = detect_model(adv.local_name, adv.manufacturer_data, device.address)
            found[device.address] = f"{name or '?':<30} {device.address}  {model or '型号未知'}  {adv.rssi} dBm"

    print(f"Listening for {seconds:.0f} s. Step on the scale to wake it up.")
    async with BleakScanner(detection_callback=on_adv, cb={"use_bdaddr": True}):
        await asyncio.sleep(seconds)
    if not found:
        print("No Etekcity scale found. Step on it while this runs, and check the distance to this computer.")
    for line in found.values():
        print(line)
