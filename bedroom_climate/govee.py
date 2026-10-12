"""Decode the Bluetooth advertisements broadcast by Govee H5075 thermo-hygrometers.

The H5075 needs no pairing or cloud account: about every two seconds it
broadcasts manufacturer-specific data under company ID 0xEC88. Bleak strips the
two company-ID bytes and hands us the remaining six:

    00 | XX XX XX | BB | 00
         |          battery % in bits 0-6, sensor-error flag in bit 7
         24-bit big-endian value: bit 23 = negative temperature,
         bits 0-22 = |temp_c| * 10000 + humidity * 10

The H5072 uses the same layout. This matches the decoder in
Bluetooth-Devices/govee-ble, which Home Assistant's Govee integration uses.
"""

from __future__ import annotations

from dataclasses import dataclass

GOVEE_COMPANY_ID = 0xEC88

# Same plausibility window govee-ble uses; anything outside is a garbled packet.
MIN_TEMP_C = -40.0
MAX_TEMP_C = 100.0


@dataclass(frozen=True)
class Reading:
    temp_c: float
    humidity: float
    battery: int


def decode_h5075(payload: bytes) -> Reading | None:
    """Decode one 0xEC88 manufacturer-data payload, or return None if it isn't valid H5075 data."""
    if len(payload) != 6:
        return None

    value = int.from_bytes(payload[1:4], "big")
    negative = value & 0x800000
    value &= 0x7FFFFF

    temp_c = (value // 1000) / 10
    if negative:
        temp_c = -temp_c
    humidity = (value % 1000) / 10

    status = payload[4]
    if status & 0x80 or not MIN_TEMP_C <= temp_c <= MAX_TEMP_C:
        return None
    return Reading(temp_c=temp_c, humidity=humidity, battery=status & 0x7F)
