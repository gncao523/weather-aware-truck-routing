"""Weather risk classification — a direct transcription of the assessment rules.

Condition thresholds (per checkpoint):

    Condition | Low        | Moderate  | High      | Severe    | No Travel
    Wind      | <25 mph    | 25–34     | 35–44     | 45–54     | ≥55 mph
    Rain      | <0.10 in/h | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00
    Snow      | <0.5 in/h  | 0.5–1.0   | 1.0–2.0   | 2.0–3.0   | >3.0

Load rules (wind only):

    ≥55 mph                   → No Travel for any load
    45–54 mph and >30,000 lb  → No Travel
    35–44 mph and >40,000 lb  → Severe

Boundary handling: each band includes its lower bound (e.g. rain 0.25 is
High, wind 35.0 is High). The top band of rain/snow is strictly greater than
its bound (">1.00", ">3.0"), so exactly 1.00 in/h of rain is Severe. Wind is
continuous, so "25–34" means 25 ≤ w < 35.

The checkpoint level is the worst of the wind, rain and snow levels after the
load rules have been applied to the wind level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self]


LEVEL_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}

# Lower bounds (inclusive) for Moderate, High, Severe, No Travel.
WIND_BOUNDS_MPH = (25.0, 35.0, 45.0, 55.0)
# Lower bounds (inclusive) for Moderate, High, Severe, then the exclusive No Travel bound.
RAIN_BOUNDS_IN_HR = (0.10, 0.25, 0.50, 1.00)
SNOW_BOUNDS_IN_HR = (0.5, 1.0, 2.0, 3.0)

NO_TRAVEL_WIND_HEAVY_LOAD_LBS = 30_000  # 45–54 mph above this → No Travel
SEVERE_WIND_HEAVY_LOAD_LBS = 40_000  # 35–44 mph above this → Severe


def wind_level(mph: float) -> RiskLevel:
    moderate, high, severe, no_travel = WIND_BOUNDS_MPH
    if mph >= no_travel:
        return RiskLevel.NO_TRAVEL
    if mph >= severe:
        return RiskLevel.SEVERE
    if mph >= high:
        return RiskLevel.HIGH
    if mph >= moderate:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def _precip_level(rate: float, bounds: tuple[float, float, float, float]) -> RiskLevel:
    moderate, high, severe, no_travel = bounds
    if rate > no_travel:
        return RiskLevel.NO_TRAVEL
    if rate >= severe:
        return RiskLevel.SEVERE
    if rate >= high:
        return RiskLevel.HIGH
    if rate >= moderate:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def rain_level(in_per_hr: float) -> RiskLevel:
    return _precip_level(in_per_hr, RAIN_BOUNDS_IN_HR)


def snow_level(in_per_hr: float) -> RiskLevel:
    return _precip_level(in_per_hr, SNOW_BOUNDS_IN_HR)


def load_adjusted_wind_level(mph: float, load_lbs: float) -> tuple[RiskLevel, str | None]:
    """Wind level after the load rules; also returns the rule that changed it, if any."""
    base = wind_level(mph)
    if base == RiskLevel.SEVERE and load_lbs > NO_TRAVEL_WIND_HEAVY_LOAD_LBS:
        return RiskLevel.NO_TRAVEL, "45–54 mph wind with load >30,000 lb → No Travel"
    if base == RiskLevel.HIGH and load_lbs > SEVERE_WIND_HEAVY_LOAD_LBS:
        return RiskLevel.SEVERE, "35–44 mph wind with load >40,000 lb → Severe"
    return base, None


@dataclass(frozen=True)
class Assessment:
    level: RiskLevel
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    load_rule: str | None = None
    drivers: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "level": int(self.level),
            "label": self.level.label,
            "wind_level": int(self.wind_level),
            "rain_level": int(self.rain_level),
            "snow_level": int(self.snow_level),
            "load_rule": self.load_rule,
            "drivers": list(self.drivers),
        }


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lbs: float) -> Assessment:
    """Classify one checkpoint. ``wind_level`` in the result already includes load rules."""
    w, rule = load_adjusted_wind_level(wind_mph, load_lbs)
    r = rain_level(rain_in_hr)
    s = snow_level(snow_in_hr)
    level = max(w, r, s)
    drivers: tuple[str, ...] = ()
    if level > RiskLevel.LOW:
        drivers = tuple(
            name for name, lvl in (("wind", w), ("rain", r), ("snow", s)) if lvl == level
        )
    return Assessment(level=level, wind_level=w, rain_level=r, snow_level=s, load_rule=rule, drivers=drivers)
