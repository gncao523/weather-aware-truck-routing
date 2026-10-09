from django.test import SimpleTestCase

from planner.services.recommendation import compute_metrics, explain, rank
from planner.services.risk import RiskLevel

L, M, H, S, NT = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


def route(rid, hours, spans):
    return compute_metrics(rid, hours * 3600, spans)


class MetricsTests(SimpleTestCase):
    def test_miles_and_distance_weighted_average(self):
        m = route("A", 10, [(50, L), (30, H), (20, S)])
        self.assertEqual(m.distance_mi, 100)
        self.assertEqual(m.high_miles, 30)
        self.assertEqual(m.severe_miles, 20)
        self.assertAlmostEqual(m.avg_risk, (30 * 2 + 20 * 3) / 100)
        self.assertEqual(m.max_level, S)


class RankingTests(SimpleTestCase):
    def test_fewest_severe_miles_beats_faster_route(self):
        fast = route("A", 8, [(90, L), (10, S)])
        slow = route("B", 12, [(60, L), (40, H)])
        self.assertEqual([m.route_id for m in rank([fast, slow])], ["B", "A"])

    def test_high_miles_break_severe_tie(self):
        a = route("A", 8, [(80, L), (20, H)])
        b = route("B", 9, [(90, L), (10, H)])
        self.assertEqual(rank([a, b])[0].route_id, "B")

    def test_average_risk_breaks_high_tie(self):
        a = route("A", 8, [(50, L), (50, M)])
        b = route("B", 9, [(90, L), (10, M)])
        self.assertEqual(rank([a, b])[0].route_id, "B")

    def test_travel_time_is_last_tiebreaker(self):
        a = route("A", 9, [(100, L)])
        b = route("B", 8, [(120, L)])
        self.assertEqual(rank([a, b])[0].route_id, "B")

    def test_no_travel_is_worse_than_severe(self):
        blocked = route("A", 8, [(99, L), (1, NT)])
        severe = route("B", 9, [(80, L), (20, S)])
        self.assertEqual(rank([blocked, severe])[0].route_id, "B")

    def test_sampling_noise_does_not_decide(self):
        a = route("A", 10, [(100, L), (5.01, H)])
        b = route("B", 9, [(100, L), (5.04, H)])  # equal at 0.1 mi resolution
        self.assertEqual(rank([a, b])[0].route_id, "B")


class ExplainTests(SimpleTestCase):
    def test_reason_names_deciding_criterion(self):
        a = route("A", 8, [(90, L), (10, S)])
        b = route("B", 12, [(100, L)])
        reasons = explain(rank([a, b]))
        self.assertEqual(len(reasons), 1)
        self.assertIn("Severe miles", reasons[0])
        self.assertIn("Route A", reasons[0])

    def test_warns_when_best_route_is_blocked(self):
        a = route("A", 8, [(90, L), (10, NT)])
        reasons = explain(rank([a]))
        self.assertTrue(reasons[0].startswith("Warning"))
