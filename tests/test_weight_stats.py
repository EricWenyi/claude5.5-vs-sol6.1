import datetime as dt
import unittest

from weight_tracker import stats
from weight_tracker.store import KG_PER_LB, Entry

D = dt.date


def days_of(pairs):
    """[(date, kg), ...] -> [Day, ...] with one weigh-in each."""
    return [stats.Day(d, kg, 1) for d, kg in pairs]


class DailyTest(unittest.TestCase):
    def test_same_day_weigh_ins_are_averaged_and_lb_converted(self):
        entries = [
            Entry(D(2026, 10, 5), 70.0, "kg", "07:00"),
            Entry(D(2026, 10, 5), 71.0, "kg", "21:00"),
            Entry(D(2026, 10, 6), 154.0, "lb"),
        ]
        days = stats.daily(entries)
        self.assertEqual([(d.date, d.n) for d in days], [(D(2026, 10, 5), 2), (D(2026, 10, 6), 1)])
        self.assertAlmostEqual(days[0].kg, 70.5)
        self.assertAlmostEqual(days[1].kg, 154 * KG_PER_LB)

    def test_rolling_uses_calendar_days_not_entry_count(self):
        days = days_of([(D(2026, 10, 1), 80), (D(2026, 10, 2), 82), (D(2026, 10, 7), 78), (D(2026, 10, 8), 76)])
        # Oct 7 still sees Oct 1 (7-day window Oct 1-7); Oct 8 doesn't.
        self.assertEqual(stats.rolling(days), [80, 81, 80, 78.66666666666667])


class PeriodTest(unittest.TestCase):
    def test_weeks_run_monday_to_sunday_and_count_each_day_once(self):
        entries = [
            Entry(D(2026, 10, 4), 80.0, "kg"),  # Sunday -> week of Sep 28
            Entry(D(2026, 10, 5), 79.0, "kg", "07:00"),  # Monday
            Entry(D(2026, 10, 5), 79.0, "kg", "08:00"),
            Entry(D(2026, 10, 5), 79.0, "kg", "09:00"),
            Entry(D(2026, 10, 11), 77.0, "kg"),  # Sunday
        ]
        weeks = stats.weekly(stats.daily(entries))
        self.assertEqual([(w.start, w.end, w.days) for w in weeks],
                         [(D(2026, 9, 28), D(2026, 10, 4), 1), (D(2026, 10, 5), D(2026, 10, 11), 2)])
        self.assertEqual(weeks[1].avg, 78.0)  # (79 + 77) / 2: three readings on Monday still count once
        self.assertEqual((weeks[1].min, weeks[1].max), (77.0, 79.0))
        self.assertEqual(weeks[1].change, -2.0)
        self.assertIsNone(weeks[0].change)

    def test_change_is_against_the_previous_calendar_period_only(self):
        days = days_of([(D(2026, 9, 1), 80), (D(2026, 10, 5), 79), (D(2026, 10, 19), 78)])
        weeks = stats.weekly(days)
        self.assertEqual([w.change for w in weeks], [None, None, None])  # a week with no weigh-ins in between
        months = stats.monthly(days)
        self.assertEqual([(m.start, m.end) for m in months], [(D(2026, 9, 1), D(2026, 9, 30)), (D(2026, 10, 1), D(2026, 10, 31))])
        self.assertEqual(months[1].avg, 78.5)
        self.assertEqual(months[1].change, -1.5)

    def test_month_ends_across_year_and_leap_february(self):
        months = stats.monthly(days_of([(D(2027, 12, 31), 80), (D(2028, 1, 1), 80), (D(2028, 2, 10), 79)]))
        self.assertEqual([m.end for m in months], [D(2027, 12, 31), D(2028, 1, 31), D(2028, 2, 29)])
        self.assertEqual(months[1].change, 0)  # December 2027 -> January 2028 are consecutive


class TrendTest(unittest.TestCase):
    def test_slope_in_kg_per_week(self):
        start = D(2026, 9, 1)
        days = days_of([(start + dt.timedelta(days=i), 80 - 0.1 * i) for i in range(0, 40, 2)])
        t = stats.trend(days)
        self.assertAlmostEqual(t["kg_per_week"], -0.7)
        self.assertEqual(t["end"], D(2026, 10, 9))
        self.assertEqual(t["start"], D(2026, 9, 13))  # only the last 28 days
        self.assertEqual(t["days"], 14)

    def test_needs_enough_days_spread_over_a_week(self):
        self.assertIsNone(stats.trend([]))
        three = days_of([(D(2026, 10, 1), 80), (D(2026, 10, 5), 79), (D(2026, 10, 9), 78)])
        self.assertIsNone(stats.trend(three))
        bunched = days_of([(D(2026, 10, d), 80) for d in range(1, 6)])
        self.assertIsNone(stats.trend(bunched))
        self.assertIsNotNone(stats.trend(days_of([(D(2026, 10, d), 80) for d in (1, 3, 5, 8)])))


class SummaryTest(unittest.TestCase):
    def test_shape(self):
        entries = [Entry(D(2026, 10, d), 170.0 - d / 10, "lb", "07:00") for d in range(1, 13)]
        s = stats.summary(entries)
        self.assertEqual(len(s["days"]), 12)
        self.assertEqual(s["days"][0], {"date": "2026-10-01", "kg": round(169.9 * KG_PER_LB, 3), "n": 1,
                                        "avg7": round(169.9 * KG_PER_LB, 3)})
        self.assertEqual([w["start"] for w in s["weeks"]], ["2026-09-28", "2026-10-05", "2026-10-12"])
        self.assertEqual(s["months"][0]["days"], 12)
        self.assertAlmostEqual(s["trend"]["kg_per_week"], -0.7 * KG_PER_LB, places=3)
        self.assertEqual(s["latest"]["weight"], 168.8)

    def test_empty(self):
        self.assertEqual(stats.summary([]), {"days": [], "weeks": [], "months": [], "trend": None, "latest": None})


if __name__ == "__main__":
    unittest.main()
