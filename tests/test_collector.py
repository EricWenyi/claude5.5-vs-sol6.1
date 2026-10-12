import unittest
from types import SimpleNamespace

from bedroom_climate.collector import GoveeCollector
from bedroom_climate.store import Store


class CollectorTest(unittest.TestCase):
    def advert(self, address, name, payload):
        return SimpleNamespace(address=address, name=name), SimpleNamespace(
            local_name=name, rssi=-70, manufacturer_data={0xEC88: payload})

    def test_locks_onto_first_sensor(self):
        c = GoveeCollector(Store(":memory:"))
        c.on_advertisement(*self.advert("AA", "GVH5075_AAAA", bytes.fromhex("0003519e6400")))
        c.on_advertisement(*self.advert("BB", "GVH5075_BBBB", bytes.fromhex("0080d2285500")))
        self.assertEqual((c.latest.device, c.latest.temp_c), ("GVH5075_AAAA", 21.7))

    def test_device_filter_matches_part_of_name(self):
        c = GoveeCollector(Store(":memory:"), device="bbbb")
        c.on_advertisement(*self.advert("AA", "GVH5075_AAAA", bytes.fromhex("0003519e6400")))
        self.assertIsNone(c.latest)
        c.on_advertisement(*self.advert("BB", "GVH5075_BBBB", bytes.fromhex("0080d2285500")))
        self.assertEqual(c.latest.temp_c, -5.3)

    def test_ignores_other_broadcasts(self):
        c = GoveeCollector(Store(":memory:"))
        device, adv = self.advert("AA", "iPhone", b"")
        adv.manufacturer_data = {0x004C: b"\x02\x15"}
        c.on_advertisement(device, adv)
        self.assertIsNone(c.latest)



if __name__ == "__main__":
    unittest.main()
