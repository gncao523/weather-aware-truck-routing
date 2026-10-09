"""Place search via Photon (OpenStreetMap data, built for search-as-you-type)."""

from __future__ import annotations

import re

from django.conf import settings
from django.core.cache import cache

from .http import get_json

COORD_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def _label(props: dict) -> str:
    name = props.get("name") or ""
    street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    parts = [name or street, props.get("city") or props.get("county"), props.get("state"), props.get("countrycode")]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return ", ".join(seen)


def search(query: str, limit: int = 6) -> list[dict]:
    """Returns ``[{label, lat, lon}]``. A literal "lat, lon" is accepted as-is."""
    query = query.strip()
    m = COORD_RE.match(query)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return [{"label": f"{lat:.5f}, {lon:.5f}", "lat": lat, "lon": lon}]

    key = f"geo:{limit}:{query.lower()}"
    if (cached := cache.get(key)) is not None:
        return cached

    data = get_json(
        f"{settings.PHOTON_URL}/api/",
        {"q": query, "limit": limit, "lang": "en"},
        provider="Geocoding service (Photon)",
        retries=1,
    )
    results = []
    for feature in data.get("features", []) if isinstance(data, dict) else []:
        lon, lat = feature["geometry"]["coordinates"]
        label = _label(feature.get("properties", {}))
        if label:
            results.append({"label": label, "lat": float(lat), "lon": float(lon)})
    cache.set(key, results, 24 * 3600)
    return results
