from django.test import SimpleTestCase

from planner.services.risk import (
    RiskLevel,
    assess,
    load_adjusted_wind_level,
    rain_level,
    snow_level,
    wind_level,
)

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


class ThresholdTests(SimpleTestCase):
    def test_wind_bands(self):
        cases = [
            (0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H),
            (45, S), (54.9, S), (55, NT), (80, NT),
        ]
        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(wind_level(mph), expected)

    def test_rain_bands(self):
        cases = [
            (0, L), (0.099, L), (0.10, M), (0.249, M), (0.25, H), (0.499, H),
            (0.50, S), (1.00, S), (1.001, NT), (2.5, NT),
        ]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(rain_level(rate), expected)

    def test_snow_bands(self):
        cases = [
            (0, L), (0.49, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H),
            (2.0, S), (3.0, S), (3.01, NT),
        ]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(snow_level(rate), expected)


class LoadRuleTests(SimpleTestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        for load in (0, 10_000, 80_000):
            self.assertEqual(load_adjusted_wind_level(55, load)[0], NT)

    def test_45_to_54_mph_over_30k_is_no_travel(self):
        self.assertEqual(load_adjusted_wind_level(45, 30_001)[0], NT)
        self.assertEqual(load_adjusted_wind_level(54.9, 45_000)[0], NT)
        # Exactly 30,000 lb is not ">30,000".
        self.assertEqual(load_adjusted_wind_level(50, 30_000)[0], S)

    def test_35_to_44_mph_over_40k_is_severe(self):
        self.assertEqual(load_adjusted_wind_level(35, 40_001)[0], S)
        self.assertEqual(load_adjusted_wind_level(44.9, 80_000)[0], S)
        self.assertEqual(load_adjusted_wind_level(40, 40_000)[0], H)
        # Between 30k and 40k the 35–44 band is unchanged.
        self.assertEqual(load_adjusted_wind_level(40, 35_000)[0], H)

    def test_load_rules_do_not_touch_other_bands(self):
        self.assertEqual(load_adjusted_wind_level(30, 100_000)[0], M)
        self.assertEqual(load_adjusted_wind_level(10, 100_000)[0], L)

    def test_rule_is_reported(self):
        level, rule = load_adjusted_wind_level(40, 45_000)
        self.assertEqual(level, S)
        self.assertIn("40,000", rule)
        self.assertIsNone(load_adjusted_wind_level(40, 20_000)[1])


class AssessTests(SimpleTestCase):
    def test_worst_condition_wins(self):
        a = assess(wind_mph=26, rain_in_hr=0.3, snow_in_hr=0, load_lbs=0)
        self.assertEqual(a.level, H)
        self.assertEqual(a.drivers, ("rain",))

    def test_load_adjustment_can_dominate(self):
        a = assess(wind_mph=46, rain_in_hr=0.6, snow_in_hr=0, load_lbs=35_000)
        self.assertEqual(a.level, NT)
        self.assertEqual(a.drivers, ("wind",))
        self.assertIsNotNone(a.load_rule)

    def test_calm_is_low(self):
        a = assess(5, 0, 0, 80_000)
        self.assertEqual(a.level, L)
        self.assertEqual(a.drivers, ())
        self.assertEqual(a.as_dict()["label"], "Low")
