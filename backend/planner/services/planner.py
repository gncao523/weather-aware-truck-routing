"""Trip planning: routes → checkpoints with ETAs → weather → risk → recommendation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.conf import settings

from . import geo, recommendation, routing, weather
from .http import UpstreamError
from .risk import RiskLevel, assess

ROUTE_IDS = "ABC"
GEOMETRY_TOLERANCE_DEG = 0.0004  # ~40 m; keeps map lines faithful while shrinking payloads
MAX_FORECAST_HOURS = 15 * 24  # Open-Meteo serves up to 16 days; keep a margin
COARSE_WEATHER_GRID_DEG = 0.1  # ~7 mi; at or below this the lookup is as fine as the forecast models


class PlanError(UpstreamError):
    """The request is valid JSON but the trip can't be planned (e.g. beyond forecast range)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=422)


@dataclass(frozen=True)
class Place:
    lat: float
    lon: float
    label: str = ""


@dataclass(frozen=True)
class TripRequest:
    origin: Place
    destination: Place
    departure: datetime  # timezone-aware
    load_lbs: float
    interval_mi: int


@dataclass
class Checkpoint:
    mile: float
    lon: float
    lat: float
    eta_offset_s: float
    span_start_mi: float
    span_end_mi: float

    @property
    def span_mi(self) -> float:
        return self.span_end_mi - self.span_start_mi


@dataclass
class BuiltRoute:
    raw: routing.RawRoute
    cum_mi: list[float]
    cum_s: list[float]  # truck-adjusted seconds from departure at each vertex
    checkpoints: list[Checkpoint] = field(default_factory=list)

    @property
    def distance_mi(self) -> float:
        return self.cum_mi[-1]

    @property
    def duration_s(self) -> float:
        return self.cum_s[-1]


def truck_segment_durations(raw: routing.RawRoute, max_speed_mph: float) -> list[float]:
    """Routing-engine segment times, slowed down wherever they imply > ``max_speed_mph``."""
    max_mps = max_speed_mph * geo.METERS_PER_MILE / 3600
    return [max(dur, dist / max_mps) for dist, dur in zip(raw.seg_distance_m, raw.seg_duration_s)]


def build_route(raw: routing.RawRoute, interval_mi: float, max_speed_mph: float) -> BuiltRoute:
    cum_mi = geo.cumulative([d / geo.METERS_PER_MILE for d in raw.seg_distance_m])
    cum_s = geo.cumulative(truck_segment_durations(raw, max_speed_mph))
    route = BuiltRoute(raw=raw, cum_mi=cum_mi, cum_s=cum_s)
    route.checkpoints = build_checkpoints(raw.coords, cum_mi, cum_s, interval_mi)
    return route


def checkpoint_miles(total_mi: float, interval_mi: float) -> list[float]:
    """0, interval, 2·interval, … plus the destination (never a sliver duplicate of it)."""
    marks = []
    k = 0
    while k * interval_mi < total_mi - 1e-6:
        marks.append(k * interval_mi)
        k += 1
    if not marks or total_mi - marks[-1] > 0.05 or len(marks) == 1:
        marks.append(total_mi)
    else:
        marks[-1] = total_mi
    return marks


def build_checkpoints(
    coords: list[geo.LonLat], cum_mi: list[float], cum_s: list[float], interval_mi: float
) -> list[Checkpoint]:
    """Checkpoints every ``interval_mi``; each one represents the miles closest to it.

    Span boundaries are the midpoints between neighbouring checkpoints, so the
    spans tile the route exactly and their lengths sum to the route length.
    """
    total = cum_mi[-1]
    marks = checkpoint_miles(total, interval_mi)
    out = []
    for i, mile in enumerate(marks):
        lon, lat = geo.interpolate_point(coords, cum_mi, mile)
        start = 0.0 if i == 0 else (marks[i - 1] + mile) / 2
        end = total if i == len(marks) - 1 else (mile + marks[i + 1]) / 2
        out.append(
            Checkpoint(
                mile=mile,
                lon=lon,
                lat=lat,
                eta_offset_s=geo.interpolate_value(cum_mi, cum_s, mile),
                span_start_mi=start,
                span_end_mi=end,
            )
        )
    return out


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(round(ts), UTC).isoformat().replace("+00:00", "Z")


def plan_trip(req: TripRequest, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    raws = routing.find_route_options((req.origin.lat, req.origin.lon), (req.destination.lat, req.destination.lon))
    built = sorted(
        (build_route(r, req.interval_mi, settings.TRUCK_MAX_SPEED_MPH) for r in raws),
        key=lambda b: b.duration_s,
    )

    dep_ts = req.departure.timestamp()
    last_arrival = dep_ts + max(b.duration_s for b in built)
    horizon = now + timedelta(hours=MAX_FORECAST_HOURS)
    if last_arrival > horizon.timestamp():
        raise PlanError(
            "This trip would end beyond the ~15-day weather forecast range. Choose an earlier departure."
        )

    points = [(cp.lat, cp.lon) for b in built for cp in b.checkpoints]
    forecasts = weather.fetch_hourly(points, dep_ts, last_arrival)

    routes_out = []
    metrics = []
    warnings: list[str] = []
    if forecasts.grid_deg > COARSE_WEATHER_GRID_DEG:
        warnings.append(
            f"Long trip: forecasts are looked up on a ~{forecasts.grid_deg * geo.MILES_PER_DEGREE_LAT:.0f}-mile grid "
            "to stay within the free weather API's limits."
        )
    it = iter(forecasts.series)
    for idx, b in enumerate(built):
        route_id = ROUTE_IDS[idx]
        cps_out = []
        spans: list[tuple[float, RiskLevel]] = []
        for n, cp in enumerate(b.checkpoints):
            eta_ts = dep_ts + cp.eta_offset_s
            sample = next(it).at(eta_ts)
            result = assess(sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr, req.load_lbs)
            spans.append((cp.span_mi, result.level))
            if sample.data_gap:
                warnings.append(f"Route {route_id} mile {cp.mile:.0f}: forecast data incomplete")
            cps_out.append(
                {
                    "index": n,
                    "mile": round(cp.mile, 2),
                    "lat": round(cp.lat, 5),
                    "lon": round(cp.lon, 5),
                    "eta": _iso(eta_ts),
                    "eta_offset_s": round(cp.eta_offset_s),
                    "span_mi": [round(cp.span_start_mi, 2), round(cp.span_end_mi, 2)],
                    "weather": sample.as_dict(),
                    "risk": result.as_dict(),
                }
            )
        m = recommendation.compute_metrics(route_id, b.duration_s, spans)
        metrics.append(m)
        keep = geo.simplify(b.raw.coords, GEOMETRY_TOLERANCE_DEG)
        routes_out.append(
            {
                "id": route_id,
                "kind": b.raw.kind,
                "distance_mi": round(b.distance_mi, 1),
                "duration_s": round(b.duration_s),
                "engine_duration_s": round(b.raw.duration_s),
                "departure": _iso(dep_ts),
                "arrival": _iso(dep_ts + b.duration_s),
                "geometry": [[round(b.raw.coords[i][0], 5), round(b.raw.coords[i][1], 5)] for i in keep],
                "time_offsets_s": [round(b.cum_s[i]) for i in keep],
                "mile_offsets": [round(b.cum_mi[i], 3) for i in keep],
                "checkpoints": cps_out,
                "summary": _summary(m),
            }
        )

    ranked = recommendation.rank(metrics)
    order = {m.route_id: i + 1 for i, m in enumerate(ranked)}
    for r in routes_out:
        r["rank"] = order[r["id"]]
    if len(routes_out) < 3:
        warnings.insert(
            0, f"Only {len(routes_out)} distinct route(s) exist between these points; showing all of them."
        )

    return {
        "generated_at": _iso(time.time()),
        "request": {
            "origin": req.origin.__dict__,
            "destination": req.destination.__dict__,
            "departure": _iso(dep_ts),
            "load_lbs": req.load_lbs,
            "interval_miles": req.interval_mi,
            "truck_max_speed_mph": settings.TRUCK_MAX_SPEED_MPH,
            "weather_grid_deg": forecasts.grid_deg,
            "weather_locations": forecasts.locations,
        },
        "routes": routes_out,
        "recommendation": {
            "route_id": ranked[0].route_id,
            "ranking": [m.route_id for m in ranked],
            "reasons": recommendation.explain(ranked),
            "criteria": [
                "Fewest No Travel miles",
                "Fewest Severe miles",
                "Fewest High miles",
                "Lowest average risk",
                "Shortest travel time",
            ],
        },
        "warnings": list(dict.fromkeys(warnings))[:20],
    }


def _summary(m: recommendation.RouteMetrics) -> dict:
    names = ("low", "moderate", "high", "severe", "no_travel")
    return {
        "miles_by_level": {n: round(m.miles_by_level[i], 1) for i, n in enumerate(names)},
        "avg_risk": round(m.avg_risk, 3),
        "max_level": int(m.max_level),
        "max_label": m.max_level.label,
    }
