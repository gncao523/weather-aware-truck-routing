"""Weather heatmap along the trip corridor for hours 0–48 after departure.

The grid is regular in *Web-Mercator* space (longitude × mercator-northing) so
that the frontend can draw one pixel per cell into a small canvas and lay it on
the map as a single image: pixel positions then match the cells exactly at
every latitude, and the GPU's bilinear filtering makes it smooth.

Only cells within ``buffer`` miles of a route are kept (the corridor). Every
cell gets a value per hour for: risk level (same rules and load as the
checkpoints), wind, rain and snow.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime

from . import geo, weather
from .risk import assess

HOURS = 48
MAX_CELLS = 160
MIN_STEP_DEG = 0.08
CORRIDOR_BUFFER_MI = 30.0
SAMPLE_STEP_MI = 5.0


def _corridor(
    samples: list[geo.LonLat], west: float, south_y: float, cols: int, rows: int, step: float, buffer_mi: float
) -> list[int]:
    cells: set[int] = set()
    for lon, lat in samples:
        ci = (lon - west) / step - 0.5
        cj = (geo.mercator_y(lat) - south_y) / step - 0.5
        cell_mi = geo.MILES_PER_DEGREE_LAT * step * math.cos(math.radians(lat))
        r = buffer_mi / cell_mi
        for j in range(max(0, math.floor(cj - r)), min(rows - 1, math.ceil(cj + r)) + 1):
            for i in range(max(0, math.floor(ci - r)), min(cols - 1, math.ceil(ci + r)) + 1):
                if (i - ci) ** 2 + (j - cj) ** 2 <= r * r:
                    cells.add(j * cols + i)
    return sorted(cells)


def build_grid(lines: Sequence[Sequence[geo.LonLat]], max_cells: int = MAX_CELLS) -> dict:
    """Choose the coarsest-needed grid whose corridor fits in ``max_cells`` cells."""
    samples = [p for line in lines for p in geo.resample(line, SAMPLE_STEP_MI)]
    lats = [p[1] for p in samples]
    lons = [p[0] for p in samples]
    mean_lat = sum(lats) / len(lats)
    cos_lat = math.cos(math.radians(mean_lat))

    step = MIN_STEP_DEG
    while True:
        cell_mi = geo.MILES_PER_DEGREE_LAT * step * cos_lat
        buffer_mi = max(CORRIDOR_BUFFER_MI, 1.5 * cell_mi)
        pad = buffer_mi / (geo.MILES_PER_DEGREE_LAT * cos_lat) + step
        west = min(lons) - pad
        east = max(lons) + pad
        south_y = geo.mercator_y(min(lats)) - pad
        north_y = geo.mercator_y(max(lats)) + pad
        cols = math.ceil((east - west) / step)
        rows = math.ceil((north_y - south_y) / step)
        cells = _corridor(samples, west, south_y, cols, rows, step, buffer_mi)
        if len(cells) <= max_cells:
            break
        step *= 1.15

    return {
        "step_deg": step,
        "cols": cols,
        "rows": rows,
        "west": west,
        "east": west + cols * step,
        "south": geo.inverse_mercator_y(south_y),
        "north": geo.inverse_mercator_y(south_y + rows * step),
        "south_y": south_y,
        "buffer_mi": buffer_mi,
        "cells": cells,
    }


def cell_center(grid: dict, index: int) -> tuple[float, float]:
    """(lat, lon) of a cell's centre."""
    j, i = divmod(index, grid["cols"])
    lon = grid["west"] + (i + 0.5) * grid["step_deg"]
    lat = geo.inverse_mercator_y(grid["south_y"] + (j + 0.5) * grid["step_deg"])
    return lat, lon


def build_heatmap(lines: Sequence[Sequence[geo.LonLat]], departure_ts: float, load_lbs: float) -> dict:
    grid = build_grid(lines)
    centers = [cell_center(grid, c) for c in grid["cells"]]
    times = [departure_ts + h * 3600 for h in range(HOURS + 1)]
    # Cells are already ≥0.08° apart and capped, so no extra snapping is needed.
    series = weather.fetch_hourly(centers, times[0], times[-1], max_locations=MAX_CELLS).series

    layers: dict[str, list[list[float]]] = {"risk": [], "wind": [], "rain": [], "snow": []}
    for ts in times:
        risk_row, wind_row, rain_row, snow_row = [], [], [], []
        for s in series:
            w = s.at(ts)
            risk_row.append(int(assess(w.wind_mph, w.rain_in_hr, w.snow_in_hr, load_lbs).level))
            wind_row.append(round(w.wind_mph, 1))
            rain_row.append(round(w.rain_in_hr, 3))
            snow_row.append(round(w.snow_in_hr, 3))
        layers["risk"].append(risk_row)
        layers["wind"].append(wind_row)
        layers["rain"].append(rain_row)
        layers["snow"].append(snow_row)

    return {
        "grid": {k: grid[k] for k in ("cols", "rows", "west", "east", "south", "north", "step_deg", "buffer_mi")},
        "cells": grid["cells"],
        "hours": list(range(HOURS + 1)),
        "times": [_iso(ts) for ts in times],
        "layers": layers,
    }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(round(ts), UTC).isoformat().replace("+00:00", "Z")
