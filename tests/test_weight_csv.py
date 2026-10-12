import datetime as dt
import unittest

from weight_tracker import csvio
from weight_tracker.store import Entry

D = dt.date
TODAY = D(2026, 10, 12)


def parse(text, unit="lb"):
    return csvio.parse(text, default_unit=unit, today=TODAY)


class ParseTest(unittest.TestCase):
    def test_withings_style_export(self):
        r = parse('Date,"Weight (kg)","Fat mass (kg)","Bone mass (kg)",Comments\n'
                  '"2026-10-11 07:31:02",75.3,15.1,3.1,\n'
                  '"2026-10-10 07:02:55",75.6,,,"after dinner"\n')
        self.assertEqual(r.errors, [])
        self.assertEqual(r.entries, [Entry(D(2026, 10, 11), 75.3, "kg", "07:31"),
                                     Entry(D(2026, 10, 10), 75.6, "kg", "07:02", "after dinner")])

    def test_header_without_unit_uses_default(self):
        r = parse("日期,体重,备注\n2026/10/11,165.4,早上\n", unit="lb")
        self.assertEqual(r.entries, [Entry(D(2026, 10, 11), 165.4, "lb", None, "早上")])

    def test_separate_time_column_and_us_dates(self):
        r = parse("Date,Time,Weight (lbs),BMI\n10/11/2026,7:05 AM,165.2,24.4\n10/10/2026,9:15 PM,166.0,24.5\n")
        self.assertEqual([(e.date, e.time, e.unit) for e in r.entries],
                         [(D(2026, 10, 11), "07:05", "lb"), (D(2026, 10, 10), "21:15", "lb")])

    def test_time_of_measurement_header(self):
        r = parse("Time of Measurement,Weight(lb),Body Fat(%)\n2026-10-11 07:10:00,165.0,22.1\n")
        self.assertEqual(r.entries, [Entry(D(2026, 10, 11), 165.0, "lb", "07:10")])

    def test_headerless_rows_with_units_in_cells(self):
        r = parse("2026-10-09,75.3kg\n2026-10-10,165.4 lb\n2026-10-11,150斤\n2026-10-12,165.0,lbs\n", unit="kg")
        self.assertEqual([(e.weight, e.unit) for e in r.entries], [(75.3, "kg"), (165.4, "lb"), (75.0, "kg"), (165.0, "lb")])

    def test_semicolons_comma_decimals_and_bom(self):
        r = parse("﻿date;weight;unit\n11.10.2026;75,3;kg\n")
        self.assertEqual(r.entries, [Entry(D(2026, 10, 11), 75.3, "kg")])

    def test_utc_timestamps_become_local_time(self):
        date, time = csvio.parse_datetime("2026-10-11T07:31:00Z")
        local = dt.datetime(2026, 10, 11, 7, 31, tzinfo=dt.timezone.utc).astimezone()
        self.assertEqual((date, time), (local.date(), local.strftime("%H:%M")))

    def test_bad_rows_are_reported_with_line_numbers(self):
        r = parse("date,weight\n2026-10-01,165\nyesterday,165\n2026-10-03,abc\n2026-10-04,16.5\n2027-01-01,165\n"
                  "2026-10-06,\n2026-10-07,165 stone\n")
        self.assertEqual(len(r.entries), 1)
        self.assertEqual(r.error_count, 5)  # the empty weight on line 7 is skipped silently
        self.assertEqual([m.split("：")[0] for m in r.errors], ["第 3 行", "第 4 行", "第 5 行", "第 6 行", "第 8 行"])
        self.assertIn("单位", r.errors[2])

    def test_unrecognisable_file(self):
        r = parse("name,score\nalice,3\n")
        self.assertEqual(r.entries, [])
        self.assertIn("找不到日期列和体重列", r.errors[0])
        self.assertEqual(parse("").errors, ["文件是空的"])

    def test_error_list_is_capped(self):
        r = parse("date,weight\n" + "nope,1\n" * 50)
        self.assertEqual((r.error_count, len(r.errors)), (50, csvio.MAX_ERRORS))


class RoundTripTest(unittest.TestCase):
    def test_dump_then_parse_gives_the_same_entries(self):
        entries = [
            Entry(D(2026, 10, 10), 165.4, "lb", "07:05", 'dinner, "late"'),
            Entry(D(2026, 10, 11), 75.25, "kg", None, "体检"),
        ]
        text = csvio.dump(entries)
        self.assertTrue(text.startswith("﻿date,time,weight,unit,note"))
        self.assertEqual(parse(text, unit="kg").entries, entries)


if __name__ == "__main__":
    unittest.main()
