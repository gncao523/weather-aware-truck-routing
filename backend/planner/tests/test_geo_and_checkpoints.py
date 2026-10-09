from django.test import SimpleTestCase

from planner.services import geo
from planner.services.planner import build_route, checkpoint_miles, truck_segment_durations
from planner.services.routing import RawRoute

MILE_M = geo.METERS_PER_MILE


def straight_route(miles: int, mph: float) -> RawRoute:
    """A due-east route made of 1-mile segments driven at a constant speed."""
    step_deg = 1 / 69.17  # ~1 mile of longitude at the equator
    coords = [(i * step_deg, 0.0) for i in range(miles + 1)]
    dist = [MILE_M] * miles
    dur = [3600 / mph] * miles
    return RawRoute(coords, dist, dur, MILE_M * miles, sum(dur), "alternative")


class GeoTests(SimpleTestCase):
    def test_haversine_known_distance(self):
        # Dallas → Chicago ≈ 802 miles great-circle.
        self.assertAlmostEqual(geo.haversine_mi(32.7767, -96.797, 41.8781, -87.6298), 802, delta=3)

    def test_interpolate_value_clamps_and_lerps(self):
        self.assertEqual(geo.interpolate_value([0, 10], [0, 100], 5), 50)
        self.assertEqual(geo.interpolate_value([0, 10], [0, 100], -1), 0)
        self.assertEqual(geo.interpolate_value([0, 10], [0, 100], 11), 100)

    def test_mercator_round_trip(self):
        for lat in (-60, 0, 33.3, 48.9):
            self.assertAlmostEqual(geo.inverse_mercator_y(geo.mercator_y(lat)), lat, places=9)

    def test_simplify_keeps_endpoints_and_corners(self):
        line = [(0, 0), (1, 0.00001), (2, 0), (2, 1)]
        self.assertEqual(geo.simplify(line, 0.001), [0, 2, 3])


class CheckpointTests(SimpleTestCase):
    def test_marks_every_interval_plus_destination(self):
        self.assertEqual(checkpoint_miles(55, 25), [0, 25, 50, 55])
        self.assertEqual(checkpoint_miles(50, 25), [0, 25, 50])
        self.assertEqual(checkpoint_miles(50.02, 25), [0, 25, 50.02])
        self.assertEqual(checkpoint_miles(8, 50), [0, 8])

    def test_spans_tile_the_route(self):
        route = build_route(straight_route(103, 50), interval_mi=10, max_speed_mph=65)
        cps = route.checkpoints
        self.assertEqual([round(c.mile) for c in cps], [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 103])
        self.assertAlmostEqual(sum(c.span_mi for c in cps), 103, places=6)
        self.assertEqual(cps[0].span_start_mi, 0)
        self.assertEqual(cps[1].span_start_mi, 5)
        self.assertEqual(cps[-1].span_end_mi, 103)

    def test_eta_follows_driving_time(self):
        route = build_route(straight_route(100, 50), interval_mi=25, max_speed_mph=65)
        etas = [c.eta_offset_s for c in route.checkpoints]
        self.assertEqual([round(e) for e in etas], [0, 1800, 3600, 5400, 7200])  # 50 mph

    def test_truck_speed_cap(self):
        raw = straight_route(10, 80)  # engine says 80 mph
        capped = truck_segment_durations(raw, 65)
        self.assertAlmostEqual(sum(capped), 10 / 65 * 3600, places=6)
        slow = truck_segment_durations(straight_route(10, 40), 65)
        self.assertAlmostEqual(sum(slow), 10 / 40 * 3600, places=6)  # never speeds up

    def test_checkpoint_position_is_on_route(self):
        route = build_route(straight_route(100, 50), interval_mi=50, max_speed_mph=65)
        mid = route.checkpoints[1]
        self.assertAlmostEqual(mid.lon, 50 / 69.17, places=6)
        self.assertEqual(mid.lat, 0)
