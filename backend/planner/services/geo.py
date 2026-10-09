"""Small, dependency-free geometry helpers.

Coordinates inside the planner are ``(lon, lat)`` tuples (GeoJSON order) unless
a function says otherwise. Distances are in statute miles.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344
MILES_PER_DEGREE_LAT = 69.0

LonLat = tuple[float, float]


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(a)))


def cumulative(values: Sequence[float]) -> list[float]:
    """Running sum starting at 0, so ``len(result) == len(values) + 1``."""
    out = [0.0]
    total = 0.0
    for v in values:
        total += v
        out.append(total)
    return out


def segment_lengths_mi(coords: Sequence[LonLat]) -> list[float]:
    return [
        haversine_mi(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:])
    ]


def _bracket(cum: Sequence[float], target: float) -> tuple[int, float]:
    """Return ``(i, t)`` such that ``target`` lies at fraction ``t`` of [cum[i-1], cum[i]]."""
    i = bisect_left(cum, target)
    i = min(max(i, 1), len(cum) - 1)
    span = cum[i] - cum[i - 1]
    t = 0.0 if span <= 0 else (target - cum[i - 1]) / span
    return i, min(max(t, 0.0), 1.0)


def interpolate_point(coords: Sequence[LonLat], cum: Sequence[float], target: float) -> LonLat:
    """Point at distance ``target`` along a polyline whose cumulative distances are ``cum``."""
    if target <= cum[0]:
        return coords[0]
    if target >= cum[-1]:
        return coords[-1]
    i, t = _bracket(cum, target)
    (x0, y0), (x1, y1) = coords[i - 1], coords[i]
    return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)


def interpolate_value(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Piecewise-linear lookup of ``y`` at ``x`` (``xs`` non-decreasing), clamped at both ends."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i, t = _bracket(xs, x)
    return ys[i - 1] + (ys[i] - ys[i - 1]) * t


def resample(coords: Sequence[LonLat], step_mi: float) -> list[LonLat]:
    """Points every ``step_mi`` along the polyline, always including both ends."""
    if len(coords) < 2:
        return list(coords)
    cum = cumulative(segment_lengths_mi(coords))
    total = cum[-1]
    n = max(1, math.ceil(total / step_mi))
    return [interpolate_point(coords, cum, total * k / n) for k in range(n + 1)]


def simplify(coords: Sequence[LonLat], tolerance_deg: float) -> list[int]:
    """Ramer-Douglas-Peucker; returns the indices of kept vertices (iterative, no recursion).

    Longitude is scaled by cos(latitude) so the tolerance is roughly isotropic.
    """
    n = len(coords)
    if n <= 2:
        return list(range(n))
    mean_lat = sum(c[1] for c in coords) / n
    kx = math.cos(math.radians(mean_lat))
    pts = [(c[0] * kx, c[1]) for c in coords]
    tol2 = tolerance_deg * tolerance_deg
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        ax, ay = pts[start]
        bx, by = pts[end]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        best_i, best_d2 = -1, -1.0
        for i in range(start + 1, end):
            px, py = pts[i]
            if seg2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / seg2
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                d2 = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d2 > best_d2:
                best_i, best_d2 = i, d2
        if best_d2 > tol2:
            keep[best_i] = True
            stack.append((start, best_i))
            stack.append((best_i, end))
    return [i for i, k in enumerate(keep) if k]


def destination_point(lat: float, lon: float, bearing_deg: float, distance_mi: float) -> LonLat:
    """Point reached travelling ``distance_mi`` from (lat, lon) on initial bearing ``bearing_deg``."""
    d = distance_mi / EARTH_RADIUS_MI
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return (((math.degrees(l2) + 540) % 360) - 180, math.degrees(p2))


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def mercator_y(lat: float) -> float:
    """Web-Mercator northing expressed in 'degrees' so it shares units with longitude."""
    lat = max(min(lat, 85.0), -85.0)
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def inverse_mercator_y(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(math.radians(y))) - math.pi / 2)
