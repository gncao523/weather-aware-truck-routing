from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from planner.services import heatmap, weather
from planner.services.weather import Forecasts, HourlySeries

T0 = 1_800_000_000 - (1_800_000_000 % 3600)  # an exact hour


def series(winds, rains, snows=None, gusts=None):
    n = len(winds)
    return HourlySeries(
        times=[T0 + i * 3600 for i in range(n)],
        wind_mph=list(winds),
        gust_mph=list(gusts or winds),
        rain_in_hr=list(rains),
        snow_in_hr=list(snows or [0.0] * n),
    )


class SeriesSamplingTests(SimpleTestCase):
    def test_wind_is_interpolated_between_hours(self):
        s = series([10, 30, 30], [0, 0, 0])
        self.assertAlmostEqual(s.at(T0 + 1800).wind_mph, 20)
        self.assertAlmostEqual(s.at(T0 + 3600).wind_mph, 30)

    def test_precip_uses_the_hour_that_contains_the_time(self):
        # Value stamped at T0+1h is the amount that fell during (T0, T0+1h].
        s = series([0, 0, 0], [0.0, 0.4, 0.05])
        self.assertEqual(s.at(T0 + 60).rain_in_hr, 0.4)
        self.assertEqual(s.at(T0 + 3600).rain_in_hr, 0.4)
        self.assertEqual(s.at(T0 + 3601).rain_in_hr, 0.05)

    def test_missing_values_are_flagged(self):
        s = series([10, None, 10], [0, 0, 0])
        sample = s.at(T0 + 1800)
        self.assertTrue(sample.data_gap)

    def test_parse_combines_rain_and_showers(self):
        item = {
            "hourly_units": {"rain": "inch", "snowfall": "inch"},
            "hourly": {
                "time": [T0, T0 + 3600],
                "wind_speed_10m": [1, 2],
                "wind_gusts_10m": [3, 4],
                "rain": [0.1, None],
                "showers": [0.05, None],
                "snowfall": [0, 0],
            },
        }
        s = weather._parse_series(item)
        self.assertAlmostEqual(s.rain_in_hr[0], 0.15)
        self.assertIsNone(s.rain_in_hr[1])


class QuotaTests(SimpleTestCase):
    """Open-Meteo bills per location, so lookups are snapped, capped and cached."""

    def setUp(self):
        cache.clear()

    def test_fine_grid_when_points_are_few(self):
        pts = [(33.0 + i * 0.1, -97.0) for i in range(20)]
        self.assertEqual(weather.snap_step(pts, 250), 0.05)

    def test_grid_coarsens_to_respect_the_cap(self):
        # ~840 checkpoints, like LA → NYC at a 10-mile interval on 3 routes.
        pts = [(34.0 + i * 0.0085, -118.0 + i * 0.054) for i in range(840)]
        step = weather.snap_step(pts, 250)
        self.assertGreater(step, 0.05)
        self.assertLessEqual(len({weather._snap(a, b, step) for a, b in pts}), 250)

    def test_nearby_points_share_one_lookup(self):
        calls = []

        def fake_batch(batch, start, end):
            calls.append(len(batch))
            return [series([5] * 80, [0.0] * 80) for _ in batch]

        pts = [(33.0, -97.0), (33.01, -97.01), (35.0, -99.0)]
        with mock.patch.object(weather, "_fetch_batch", side_effect=fake_batch):
            out = weather.fetch_hourly(pts, T0, T0 + 5 * 3600)
        self.assertEqual(calls, [2])
        self.assertEqual(out.locations, 2)
        self.assertEqual(len(out.series), 3)
        self.assertIs(out.series[0], out.series[1])

    def test_similar_departures_reuse_the_cache(self):
        calls = []

        def fake_batch(batch, start, end):
            calls.append(len(batch))
            return [series([5] * 80, [0.0] * 80) for _ in batch]

        pts = [(33.0, -97.0)]
        with mock.patch.object(weather, "_fetch_batch", side_effect=fake_batch):
            weather.fetch_hourly(pts, T0 + 600, T0 + 10 * 3600)
            weather.fetch_hourly(pts, T0 + 1200, T0 + 10 * 3600 + 900)  # 10 min later, slightly longer trip
        self.assertEqual(calls, [1])


class LocationBudgetTests(SimpleTestCase):
    def test_allows_up_to_the_limit_then_refuses(self):
        b = weather.LocationBudget(per_minute=100)
        b.acquire(60)
        b.acquire(40)
        with self.assertRaises(weather.WeatherError) as ctx:
            b.acquire(1, max_wait=0)
        self.assertEqual(ctx.exception.status_code, 503)

    def test_old_usage_expires_after_a_minute(self):
        b = weather.LocationBudget(per_minute=100)
        with mock.patch.object(weather.time, "monotonic", return_value=1000.0):
            b.acquire(100)
        with mock.patch.object(weather.time, "monotonic", return_value=1061.0):
            b.acquire(100, max_wait=0)  # previous usage has aged out


class HeatmapGridTests(SimpleTestCase):
    LINE = [(-96.8, 32.78), (-92.0, 36.0), (-87.63, 41.88)]

    def test_corridor_is_bounded_and_near_route(self):
        grid = heatmap.build_grid([self.LINE], max_cells=300)
        self.assertLessEqual(len(grid["cells"]), 300)
        self.assertGreater(len(grid["cells"]), 20)
        for c in grid["cells"]:
            lat, lon = heatmap.cell_center(grid, c)
            self.assertTrue(grid["south"] <= lat <= grid["north"])
            self.assertTrue(grid["west"] <= lon <= grid["east"])

    def test_endpoints_are_inside_corridor(self):
        grid = heatmap.build_grid([self.LINE])
        cells = set(grid["cells"])
        for lon, lat in (self.LINE[0], self.LINE[-1]):
            i = int((lon - grid["west"]) / grid["step_deg"])
            j = int((heatmap.geo.mercator_y(lat) - grid["south_y"]) / grid["step_deg"])
            self.assertIn(j * grid["cols"] + i, cells)

    def test_build_heatmap_has_49_hours_per_layer(self):
        def fake_fetch(points, start, end, max_locations=None):
            return Forecasts([series([50] * 60, [0.0] * 60) for _ in points], 0.05, len(points))

        with mock.patch.object(weather, "fetch_hourly", side_effect=fake_fetch):
            out = heatmap.build_heatmap([self.LINE], T0 + 3600, load_lbs=35_000)
        self.assertEqual(len(out["hours"]), 49)
        self.assertEqual(len(out["layers"]["risk"]), 49)
        self.assertEqual(len(out["layers"]["risk"][0]), len(out["cells"]))
        # 50 mph with 35,000 lb → No Travel (load rule), same as checkpoints.
        self.assertEqual(set(out["layers"]["risk"][0]), {4})
