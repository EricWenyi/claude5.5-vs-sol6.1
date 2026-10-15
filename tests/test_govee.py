import unittest

from home_dashboard.modules.climate.govee import Reading, decode_h5075


class DecodeH5075Test(unittest.TestCase):
    def test_room_temperature(self):
        # 0x03519E = 217502 -> 21.7 °C, 50.2 %; battery byte 0x64 = 100 %
        self.assertEqual(decode_h5075(bytes.fromhex("0003519e6400")), Reading(21.7, 50.2, 100))

    def test_negative_temperature(self):
        # Bit 23 marks a negative value: 0x800000 | 53800 -> -5.3 °C, 80.0 %
        self.assertEqual(decode_h5075(bytes.fromhex("0080d2285500")), Reading(-5.3, 80.0, 85))

    def test_error_flag_is_rejected(self):
        self.assertIsNone(decode_h5075(bytes.fromhex("0003519ee400")))

    def test_out_of_range_temperature_is_rejected(self):
        # 1_005_000 -> 100.5 °C, beyond what the sensor can report
        self.assertIsNone(decode_h5075(bytes([0]) + (1_005_000).to_bytes(3, "big") + bytes([0x64, 0])))

    def test_real_h5075_on_macos(self):
        # Heard from GVH5075_2186 on macOS 26 (bleak 3.0.2). CoreBluetooth glues the sensor's
        # Apple iBeacon ("INTELLI_ROCKS_HW") onto the Govee data. The sensor's own screen,
        # photographed about 5 minutes later, showed 21.7 °C and 52 % (whole percent only).
        payload = bytes.fromhex("000351a764004c000215494e54454c4c495f524f434b535f48575075f2ffc2")
        self.assertEqual(decode_h5075(payload), Reading(21.7, 51.1, 100))

    def test_other_payload_lengths_are_ignored(self):
        # H5074 and other models also use 0xEC88, with different layouts.
        self.assertIsNone(decode_h5075(bytes.fromhex("0003519e64")))
        self.assertIsNone(decode_h5075(bytes.fromhex("0003519e640000")))


if __name__ == "__main__":
    unittest.main()
