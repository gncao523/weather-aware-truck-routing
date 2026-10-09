"""Hourly forecasts from Open-Meteo, sampled at arbitrary times.

* Units are requested directly in mph and inches.
* Rain = ``rain`` (large-scale) + ``showers`` (convective); snow = ``snowfall``.
  Open-Meteo reports both as the amount fallen during the *preceding* hour, so the
  value stamped at hour H is the rate in in/hr for the interval (H-1h, H].
* Wind is an instantaneous value and is linearly interpolated between hours.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from bisect import bisect_left
from collections import deque
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache

from .http import UpstreamError, get_json

logger = logging.getLogger(__name__)

HOURLY_VARS = ("wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall")
BATCH_SIZE = 50  # locations per Open-Meteo request (~2 s each when not throttled)
MAX_WORKERS = 4
REQUEST_TIMEOUT_S = 40
BUDGET_MAX_WAIT_S = 20
HOUR = 3600
WINDOW_BLOCK = 6 * HOUR
# Distinct locations per plan call (the heatmap uses its own cap of 160). A plan plus
# its heatmap costs ≤ 440 locations, under the 500/minute OPEN_METEO_LOCATIONS_PER_MINUTE budget.
MAX_LOCATIONS_PER_CALL = 280
SNAP_STEPS_DEG = (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.75, 1.0)


class WeatherError(UpstreamError):
    pass


class LocationBudget:
    """Sliding one-minute budget of locations sent to Open-Meteo, shared by all threads.

    Open-Meteo bills each location in a request and starts throttling (slow
    responses, then HTTP 429) once a client exceeds its per-minute allowance.
    Waiting for room here is better than being throttled, and failing fast with
    a clear message is better than a request that hangs.
    """

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._events: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def acquire(self, n: int, max_wait: float = BUDGET_MAX_WAIT_S) -> None:
        deadline = time.monotonic() + max_wait
        while True:
            with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0][0] >= 60:
                    self._events.popleft()
                used = sum(k for _, k in self._events)
                if used + n <= self.per_minute or not self._events:
                    self._events.append((now, n))
                    return
                wait = 60 - (now - self._events[0][0])
            if now + wait > deadline:
                raise WeatherError(
                    "The weather service is busy (free-tier rate limit). Please try again in a minute.", 503
                )
            time.sleep(min(wait, 1.0))


_budget: LocationBudget | None = None
_budget_lock = threading.Lock()


def budget() -> LocationBudget:
    global _budget
    with _budget_lock:
        if _budget is None or _budget.per_minute != settings.OPEN_METEO_LOCATIONS_PER_MINUTE:
            _budget = LocationBudget(settings.OPEN_METEO_LOCATIONS_PER_MINUTE)
        return _budget


@dataclass(frozen=True)
class WeatherSample:
    wind_mph: float
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float
    data_gap: bool = False

    def as_dict(self) -> dict:
        return {
            "wind_mph": round(self.wind_mph, 1),
            "gust_mph": round(self.gust_mph, 1),
            "rain_in_hr": round(self.rain_in_hr, 3),
            "snow_in_hr": round(self.snow_in_hr, 3),
            "data_gap": self.data_gap,
        }


@dataclass
class HourlySeries:
    times: list[int]  # unix seconds, ascending, hourly
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in_hr: list[float | None]
    snow_in_hr: list[float | None]

    def at(self, ts: float) -> WeatherSample:
        times = self.times
        k = bisect_left(times, ts)  # first hour stamp >= ts
        gap = False

        # Wind: linear interpolation between the surrounding hourly instants.
        if k <= 0 or k >= len(times):
            idx = 0 if k <= 0 else len(times) - 1
            wind, g1 = _value(self.wind_mph, idx)
            gust, g2 = _value(self.gust_mph, idx)
            gap = g1 or g2 or abs(times[idx] - ts) > HOUR
        else:
            t = (ts - times[k - 1]) / (times[k] - times[k - 1])
            w0, a = _value(self.wind_mph, k - 1)
            w1, b = _value(self.wind_mph, k)
            u0, c = _value(self.gust_mph, k - 1)
            u1, d = _value(self.gust_mph, k)
            wind, gust = w0 + (w1 - w0) * t, u0 + (u1 - u0) * t
            gap = a or b or c or d

        # Precipitation: the hourly bucket that contains ts, i.e. stamped at the next hour.
        p = min(max(k, 0), len(times) - 1)
        rain, g3 = _value(self.rain_in_hr, p)
        snow, g4 = _value(self.snow_in_hr, p)
        return WeatherSample(wind, gust, rain, snow, gap or g3 or g4)

    def to_cache(self) -> dict:
        return self.__dict__.copy()


def _value(values: list[float | None], i: int) -> tuple[float, bool]:
    v = values[i]
    return (0.0, True) if v is None else (float(v), False)


def _hour_floor(ts: float) -> int:
    return int(math.floor(ts / HOUR) * HOUR)


def _iso_hour(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M")


def snap_step(points: Sequence[tuple[float, float]], max_unique: int) -> float:
    """Finest grid (degrees) on which ``points`` collapse to at most ``max_unique`` locations."""
    for step in SNAP_STEPS_DEG:
        if len({_snap(lat, lon, step) for lat, lon in points}) <= max_unique:
            return step
    return SNAP_STEPS_DEG[-1]


def _snap(lat: float, lon: float, step: float) -> tuple[float, float]:
    return round(round(lat / step) * step, 4), round(round(lon / step) * step, 4)


@dataclass
class Forecasts:
    series: list[HourlySeries]  # one per input point, in input order
    grid_deg: float  # forecast lookup resolution actually used
    locations: int  # distinct locations looked up


def fetch_hourly(
    points: Sequence[tuple[float, float]],
    start_ts: float,
    end_ts: float,
    max_locations: int = MAX_LOCATIONS_PER_CALL,
) -> Forecasts:
    """Hourly series covering [start_ts, end_ts] for each (lat, lon) point.

    Open-Meteo bills every location in a request (free tier: 600/minute,
    10,000/day), so points are snapped to a grid — 0.05° (~3 mi) normally,
    coarser only when needed to stay within ``max_locations``. The forecast
    models themselves are 3–13 km, so the finest steps lose nothing.

    The time window is aligned to 6-hour blocks so repeated plans for similar
    departure times hit the cache instead of the API.
    """
    start = _hour_floor(start_ts) - HOUR
    end = start + math.ceil((end_ts + 2 * HOUR - start) / WINDOW_BLOCK) * WINDOW_BLOCK
    step = snap_step(points, max_locations)
    keys = [_snap(lat, lon, step) for lat, lon in points]

    results: dict[tuple[float, float], HourlySeries] = {}
    missing: list[tuple[float, float]] = []
    for key in dict.fromkeys(keys):  # unique, order-preserving
        cached = cache.get(_cache_key(key, start, end))
        if cached is not None:
            results[key] = HourlySeries(**cached)
        else:
            missing.append(key)

    batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
    if batches:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batches))) as pool:
            for batch, series_list in zip(batches, pool.map(lambda b: _fetch_batch(b, start, end), batches)):
                for key, series in zip(batch, series_list):
                    results[key] = series
                    cache.set(_cache_key(key, start, end), series.to_cache(), settings.WEATHER_CACHE_SECONDS)

    return Forecasts(series=[results[k] for k in keys], grid_deg=step, locations=len(results))


def _cache_key(key: tuple[float, float], start: int, end: int) -> str:
    return f"wx:{key[0]}:{key[1]}:{start}:{end}"


def _fetch_batch(batch: list[tuple[float, float]], start: int, end: int) -> list[HourlySeries]:
    params = {
        "latitude": ",".join(f"{lat}" for lat, _ in batch),
        "longitude": ",".join(f"{lon}" for _, lon in batch),
        "hourly": ",".join(HOURLY_VARS),
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "GMT",
        "timeformat": "unixtime",
        "start_hour": _iso_hour(start),
        "end_hour": _iso_hour(end),
    }
    url = settings.OPEN_METEO_URL
    if settings.OPEN_METEO_API_KEY:
        params["apikey"] = settings.OPEN_METEO_API_KEY
        url = url.replace("://api.", "://customer-api.")
    budget().acquire(len(batch))
    try:
        # One retry only: every retry is billed again and adds to any throttling.
        data = get_json(url, params, provider="Weather service (Open-Meteo)", retries=1, timeout=REQUEST_TIMEOUT_S)
    except UpstreamError as exc:
        raise WeatherError(str(exc), exc.status_code) from exc

    items = data if isinstance(data, list) else [data]
    if len(items) != len(batch):
        raise WeatherError("Weather service returned an unexpected number of locations")
    return [_parse_series(item) for item in items]


def _parse_series(item: dict) -> HourlySeries:
    if item.get("error"):
        raise WeatherError(f"Weather service error: {item.get('reason', 'unknown')}")
    units = item.get("hourly_units", {})
    if units.get("rain") not in (None, "inch") or units.get("snowfall") not in (None, "inch"):
        raise WeatherError("Weather service returned unexpected units")
    h = item["hourly"]
    rain = [
        None if r is None and s is None else (r or 0.0) + (s or 0.0)
        for r, s in zip(h["rain"], h["showers"])
    ]
    return HourlySeries(
        times=[int(t) for t in h["time"]],
        wind_mph=h["wind_speed_10m"],
        gust_mph=h["wind_gusts_10m"],
        rain_in_hr=rain,
        snow_in_hr=h["snowfall"],
    )
