"""Route recommendation.

Routes are ranked lexicographically, as the assessment specifies:

    1. Fewest Severe miles
    2. Fewest High miles
    3. Lowest average risk (distance-weighted, Low=0 … No Travel=4)
    4. Shortest travel time

"No Travel" is stricter than Severe, so before rule 1 we compare miles of No
Travel conditions — a route that the load rules forbid is never preferred over
one that is merely Severe. Miles are compared at 0.1 mi resolution and average
risk at 0.01 so sampling noise does not decide a tie.
"""

from __future__ import annotations

from dataclasses import dataclass

from .risk import LEVEL_LABELS, RiskLevel


@dataclass(frozen=True)
class RouteMetrics:
    route_id: str
    duration_s: float
    distance_mi: float
    miles_by_level: tuple[float, float, float, float, float]  # indexed by RiskLevel
    avg_risk: float
    max_level: RiskLevel

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]


CRITERIA = (
    ("no_travel_miles", "No Travel miles", lambda m: round(m.no_travel_miles, 1)),
    ("severe_miles", "Severe miles", lambda m: round(m.severe_miles, 1)),
    ("high_miles", "High miles", lambda m: round(m.high_miles, 1)),
    ("avg_risk", "average risk", lambda m: round(m.avg_risk, 2)),
    ("duration_s", "travel time", lambda m: round(m.duration_s)),
)


def sort_key(m: RouteMetrics) -> tuple:
    return tuple(fn(m) for _, _, fn in CRITERIA)


def rank(metrics: list[RouteMetrics]) -> list[RouteMetrics]:
    return sorted(metrics, key=sort_key)


def compute_metrics(
    route_id: str, duration_s: float, spans: list[tuple[float, RiskLevel]]
) -> RouteMetrics:
    """``spans`` are (miles, level) pieces that together cover the whole route."""
    miles = [0.0] * len(RiskLevel)
    for length, level in spans:
        miles[level] += length
    total = sum(miles)
    avg = sum(length * int(level) for length, level in spans) / total if total else 0.0
    max_level = max((lvl for length, lvl in spans if length > 0), default=RiskLevel.LOW)
    return RouteMetrics(route_id, duration_s, total, tuple(miles), avg, max_level)


def _fmt(key: str, m: RouteMetrics) -> str:
    if key == "duration_s":
        h, rem = divmod(round(m.duration_s / 60), 60)
        return f"{h}h {rem:02d}m"
    if key == "avg_risk":
        return f"{m.avg_risk:.2f}"
    return f"{getattr(m, key):.1f} mi"


def explain(ranked: list[RouteMetrics]) -> list[str]:
    """Human-readable reasons the first route beats each of the others."""
    if not ranked:
        return []
    best = ranked[0]
    reasons = []
    for other in ranked[1:]:
        for key, label, fn in CRITERIA:
            if fn(best) != fn(other):
                reasons.append(
                    f"Beats Route {other.route_id} on {label}: {_fmt(key, best)} vs {_fmt(key, other)}"
                    + _tie_note(key)
                )
                break
        else:
            reasons.append(f"Ties Route {other.route_id} on every criterion")
    if best.max_level >= RiskLevel.NO_TRAVEL:
        reasons.insert(0, "Warning: every route hits No Travel conditions — consider delaying departure")
    elif best.max_level >= RiskLevel.SEVERE:
        reasons.insert(0, f"Caution: recommended route still has {LEVEL_LABELS[best.max_level]} segments")
    return reasons


def _tie_note(key: str) -> str:
    keys = [k for k, _, _ in CRITERIA]
    previous = [label for _, label, _ in CRITERIA[: keys.index(key)]]
    return f" (tied on {', '.join(previous)})" if previous else ""
