"""Route options from an OSRM server.

OSRM's ``alternatives`` frequently returns fewer than three routes (especially
on long trips), so when it does we ask for detours through via-points offset
to either side of the fastest route's midpoint, and keep only candidates that
are genuinely different (low overlap) and not absurdly long.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from django.conf import settings

from . import geo
from .http import UpstreamError, get_json

logger = logging.getLogger(__name__)

MAX_DETOUR_RATIO = 1.6  # candidate duration/distance vs the fastest route
MAX_SHARED_FRACTION = 0.85  # candidate must have ≥15% of its length on different roads
OVERLAP_SAMPLE_MI = 0.5
OVERLAP_CELL_DEG = 0.01  # ~0.7 mi grid used to compare routes
DETOUR_OFFSETS = (0.15, -0.15, 0.3, -0.3)  # fraction of straight-line trip length


class RoutingError(UpstreamError):
    """No usable route (bad input, unroutable points) or the routing API failed."""


@dataclass
class RawRoute:
    coords: list[geo.LonLat]
    seg_distance_m: list[float]  # one entry per coordinate pair
    seg_duration_s: list[float]
    distance_m: float
    duration_s: float
    kind: str  # "alternative" (OSRM) or "detour" (via-point)


_throttle_lock = threading.Lock()
_last_call = 0.0


def _throttle(min_interval: float) -> None:
    """The public OSRM demo server asks for at most ~1 request/second."""
    global _last_call
    with _throttle_lock:
        wait = _last_call + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _osrm_route(waypoints: list[tuple[float, float]], alternatives: int, kind: str) -> list[RawRoute]:
    """``waypoints`` are (lat, lon). Returns [] when OSRM finds no route."""
    if "router.project-osrm.org" in settings.OSRM_URL:
        _throttle(1.0)
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "distance,duration",
        "steps": "false",
    }
    if alternatives:
        params["alternatives"] = str(alternatives)
    data = get_json(
        f"{settings.OSRM_URL}/route/v1/driving/{coords}",
        params,
        provider="Routing service (OSRM)",
        json_client_errors=True,
    )
    code = data.get("code") if isinstance(data, dict) else None
    if code in {"NoRoute", "NoSegment"}:
        return []
    if code != "Ok":
        message = data.get("message", "unexpected response") if isinstance(data, dict) else "bad response"
        raise RoutingError(f"Routing service error: {message}")
    return [_parse_route(r, kind) for r in data.get("routes", [])]


def _parse_route(route: dict, kind: str) -> RawRoute:
    coords = [(float(lon), float(lat)) for lon, lat in route["geometry"]["coordinates"]]
    dist: list[float] = []
    dur: list[float] = []
    for leg in route.get("legs", []):
        ann = leg.get("annotation") or {}
        dist.extend(ann.get("distance", []))
        dur.extend(ann.get("duration", []))
    total_m = float(route["distance"])
    total_s = float(route["duration"])
    if len(dist) != len(coords) - 1 or len(dur) != len(coords) - 1:
        # Annotations don't line up with the geometry: fall back to geodesic
        # lengths and spread the duration proportionally.
        lengths = [mi * geo.METERS_PER_MILE for mi in geo.segment_lengths_mi(coords)]
        length_sum = sum(lengths) or 1.0
        dist = lengths
        dur = [total_s * d / length_sum for d in lengths]
    return RawRoute(coords, dist, dur, total_m, total_s, kind)


def _cells(route: RawRoute) -> set[tuple[int, int]]:
    pts = geo.resample(route.coords, OVERLAP_SAMPLE_MI)
    return {(round(lon / OVERLAP_CELL_DEG), round(lat / OVERLAP_CELL_DEG)) for lon, lat in pts}


def _dilate(cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
    return {(x + dx, y + dy) for x, y in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


def shared_fraction(candidate: set[tuple[int, int]], existing_dilated: set[tuple[int, int]]) -> float:
    """Fraction of the candidate's cells that lie on (or right next to) an existing route."""
    if not candidate:
        return 1.0
    return len(candidate & existing_dilated) / len(candidate)


def find_route_options(
    origin: tuple[float, float], destination: tuple[float, float], count: int = 3
) -> list[RawRoute]:
    """Up to ``count`` distinct routes, origin/destination given as (lat, lon)."""
    routes = _osrm_route([origin, destination], alternatives=count, kind="alternative")
    if not routes:
        raise RoutingError("No drivable route was found between these locations.", status_code=422)

    fastest = min(routes, key=lambda r: r.duration_s)
    accepted: list[RawRoute] = []
    accepted_cells: list[set[tuple[int, int]]] = []

    def try_add(candidate: RawRoute) -> bool:
        if (
            candidate.duration_s > fastest.duration_s * MAX_DETOUR_RATIO
            or candidate.distance_m > fastest.distance_m * MAX_DETOUR_RATIO
        ):
            return False
        cells = _cells(candidate)
        if any(shared_fraction(cells, _dilate(c)) > MAX_SHARED_FRACTION for c in accepted_cells):
            return False
        accepted.append(candidate)
        accepted_cells.append(cells)
        return True

    for r in sorted(routes, key=lambda r: r.duration_s):
        if len(accepted) < count:
            try_add(r)

    if len(accepted) < count:
        for via in _detour_points(fastest, origin, destination):
            if len(accepted) >= count:
                break
            try:
                candidates = _osrm_route([origin, via, destination], alternatives=0, kind="detour")
            except UpstreamError as exc:
                logger.warning("Detour request failed: %s", exc)
                continue
            for c in candidates[:1]:
                try_add(c)

    return accepted


def _detour_points(
    fastest: RawRoute, origin: tuple[float, float], destination: tuple[float, float]
) -> list[tuple[float, float]]:
    """Via-points (lat, lon) perpendicular to the trip, centred on the fastest route's midpoint."""
    cum = geo.cumulative(geo.segment_lengths_mi(fastest.coords))
    mid_lon, mid_lat = geo.interpolate_point(fastest.coords, cum, cum[-1] / 2)
    straight = geo.haversine_mi(origin[0], origin[1], destination[0], destination[1])
    bearing = geo.initial_bearing(origin[0], origin[1], destination[0], destination[1])
    points = []
    for frac in DETOUR_OFFSETS:
        offset = min(max(abs(frac) * straight, 5.0), 200.0)
        side = 90 if frac > 0 else -90
        lon, lat = geo.destination_point(mid_lat, mid_lon, bearing + side, offset)
        points.append((lat, lon))
    return points
