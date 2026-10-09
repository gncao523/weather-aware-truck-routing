from datetime import UTC, datetime, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from planner.services import routing, weather
from planner.services.routing import RawRoute
from planner.services.weather import Forecasts, HourlySeries

MILE_M = 1609.344


def fake_route(miles: int, mph: float, lat: float) -> RawRoute:
    coords = [(-97 + i / 69.17, lat) for i in range(miles + 1)]
    return RawRoute(coords, [MILE_M] * miles, [3600 / mph] * miles, MILE_M * miles, miles / mph * 3600, "alternative")


def windy_fetch(points, start, end, max_locations=None):
    """Calm everywhere except south of 32.9°N, where it blows 40 mph."""
    t0 = int(start // 3600 * 3600) - 3600
    n = int((end - t0) // 3600) + 4
    out = []
    for lat, _ in points:
        w = 40.0 if lat < 32.9 else 5.0
        out.append(HourlySeries([t0 + i * 3600 for i in range(n)], [w] * n, [w] * n, [0.0] * n, [0.0] * n))
    return Forecasts(out, grid_deg=0.05, locations=len(out))


class PlanApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.body = {
            "origin": {"lat": 33.0, "lon": -97.0, "label": "A"},
            "destination": {"lat": 33.0, "lon": -95.6, "label": "B"},
            "departure": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "load_lbs": 45_000,
            "interval_miles": 10,
        }

    def _post(self, body=None):
        routes = [fake_route(100, 60, 32.8), fake_route(110, 55, 33.0), fake_route(120, 50, 33.1)]
        with (
            mock.patch.object(routing, "find_route_options", return_value=routes),
            mock.patch.object(weather, "fetch_hourly", side_effect=windy_fetch),
        ):
            return self.client.post("/api/plan/", body or self.body, format="json")

    def test_plan_recommends_safer_route_over_faster_one(self):
        res = self._post()
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(len(data["routes"]), 3)
        by_id = {r["id"]: r for r in data["routes"]}
        # Route A is the fastest but runs through 40 mph wind with 45,000 lb → Severe.
        self.assertEqual(by_id["A"]["summary"]["miles_by_level"]["severe"], 100)
        self.assertEqual(by_id["A"]["checkpoints"][0]["risk"]["label"], "Severe")
        self.assertEqual(data["recommendation"]["route_id"], "B")
        self.assertEqual(data["recommendation"]["ranking"], ["B", "C", "A"])
        self.assertEqual(len(by_id["A"]["checkpoints"]), 11)  # every 10 mi incl. both ends

    def test_eta_matches_departure_plus_drive_time(self):
        data = self._post().json()
        route = data["routes"][0]
        dep = datetime.fromisoformat(route["departure"].replace("Z", "+00:00"))
        last = route["checkpoints"][-1]
        eta = datetime.fromisoformat(last["eta"].replace("Z", "+00:00"))
        self.assertAlmostEqual((eta - dep).total_seconds(), route["duration_s"], delta=1)

    def test_validation_errors(self):
        bad = dict(self.body, interval_miles=15)
        self.assertEqual(self._post(bad).status_code, 400)
        bad = dict(self.body, departure=(datetime.now(UTC) + timedelta(days=9)).isoformat())
        self.assertEqual(self._post(bad).status_code, 400)
        bad = dict(self.body, destination=self.body["origin"])
        self.assertEqual(self._post(bad).status_code, 400)

    def test_upstream_failure_is_reported(self):
        with mock.patch.object(
            routing, "find_route_options", side_effect=routing.RoutingError("No drivable route", 422)
        ):
            res = self.client.post("/api/plan/", self.body, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertIn("No drivable route", res.json()["detail"])


class GeocodeApiTests(SimpleTestCase):
    def test_literal_coordinates_skip_the_network(self):
        res = APIClient().get("/api/geocode/", {"q": "32.7767, -96.797"})
        self.assertEqual(res.json()["results"][0]["lat"], 32.7767)


class RouteDedupTests(SimpleTestCase):
    def test_identical_routes_overlap_fully(self):
        a = routing._cells(fake_route(50, 60, 33.0))
        self.assertGreater(routing.shared_fraction(a, routing._dilate(a)), 0.99)

    def test_parallel_routes_far_apart_do_not_overlap(self):
        a = routing._cells(fake_route(50, 60, 33.0))
        b = routing._cells(fake_route(50, 60, 33.5))
        self.assertEqual(routing.shared_fraction(a, routing._dilate(b)), 0)
