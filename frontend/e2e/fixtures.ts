/**
 * Deterministic API responses for the browser tests, shaped exactly like the
 * Django API's. Route A is the fastest but crosses 35–44 mph wind with a heavy
 * load (→ Severe), so the safer Route B must be recommended.
 */
import type { Checkpoint, HeatmapResponse, LonLat, PlanResponse, RiskLevel, RouteOption } from "../src/types";

const LABELS = ["Low", "Moderate", "High", "Severe", "No Travel"];
const DEPARTURE = "2030-01-15T14:00:00Z";
const ORIGIN = { label: "Denver, Colorado, US", lat: 39.7392, lon: -104.9903 };
const DESTINATION = { label: "Salt Lake City, Utah, US", lat: 40.7608, lon: -111.891 };

function buildRoute(
  id: string,
  rank: number,
  miles: number,
  mph: number,
  bendLat: number,
  levels: RiskLevel[],
): RouteOption {
  const n = 20;
  const geometry: LonLat[] = [];
  const mileOffsets: number[] = [];
  const timeOffsets: number[] = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n;
    geometry.push([
      ORIGIN.lon + (DESTINATION.lon - ORIGIN.lon) * f,
      ORIGIN.lat + (DESTINATION.lat - ORIGIN.lat) * f + Math.sin(Math.PI * f) * bendLat,
    ]);
    mileOffsets.push(miles * f);
    timeOffsets.push(((miles * f) / mph) * 3600);
  }
  const step = miles / (levels.length - 1);
  const marks = levels.map((_, i) => i * step);
  const checkpoints: Checkpoint[] = levels.map((level, i) => {
    const mile = marks[i];
    const f = mile / miles;
    const heavyWind = level === 3;
    return {
      index: i,
      mile,
      lat: ORIGIN.lat + (DESTINATION.lat - ORIGIN.lat) * f + Math.sin(Math.PI * f) * bendLat,
      lon: ORIGIN.lon + (DESTINATION.lon - ORIGIN.lon) * f,
      eta: new Date(Date.parse(DEPARTURE) + (mile / mph) * 3600e3).toISOString(),
      eta_offset_s: Math.round((mile / mph) * 3600),
      span_mi: [i === 0 ? 0 : (marks[i - 1] + mile) / 2, i === levels.length - 1 ? miles : (mile + marks[i + 1]) / 2],
      weather: {
        wind_mph: heavyWind ? 38 : level === 2 ? 36 : 8,
        gust_mph: heavyWind ? 52 : 15,
        rain_in_hr: level === 1 ? 0.12 : 0,
        snow_in_hr: 0,
        data_gap: false,
      },
      risk: {
        level,
        label: LABELS[level],
        wind_level: heavyWind ? 3 : level === 2 ? 2 : 0,
        rain_level: level === 1 ? 1 : 0,
        snow_level: 0,
        load_rule: heavyWind ? "35–44 mph wind with load >40,000 lb → Severe" : null,
        drivers: level ? [level === 1 ? "rain" : "wind"] : [],
      },
    };
  });
  const byLevel = [0, 0, 0, 0, 0];
  checkpoints.forEach((c) => (byLevel[c.risk.level] += c.span_mi[1] - c.span_mi[0]));
  const avg = byLevel.reduce((s, m, lvl) => s + m * lvl, 0) / miles;
  const max = Math.max(...levels) as RiskLevel;
  return {
    id,
    kind: "alternative",
    distance_mi: miles,
    duration_s: Math.round((miles / mph) * 3600),
    engine_duration_s: Math.round((miles / mph) * 3600),
    departure: DEPARTURE,
    arrival: new Date(Date.parse(DEPARTURE) + (miles / mph) * 3600e3).toISOString(),
    geometry,
    time_offsets_s: timeOffsets,
    mile_offsets: mileOffsets,
    checkpoints,
    summary: {
      miles_by_level: { low: byLevel[0], moderate: byLevel[1], high: byLevel[2], severe: byLevel[3], no_travel: byLevel[4] },
      avg_risk: avg,
      max_level: max,
      max_label: LABELS[max],
    },
    rank,
  };
}

export const plan: PlanResponse = {
  generated_at: "2030-01-15T13:00:00Z",
  request: {
    origin: ORIGIN,
    destination: DESTINATION,
    departure: DEPARTURE,
    load_lbs: 42000,
    interval_miles: 25,
    truck_max_speed_mph: 65,
  },
  routes: [
    buildRoute("A", 3, 500, 60, 0.0, [0, 0, 0, 3, 3, 0, 0, 0, 0, 0, 0]),
    buildRoute("B", 1, 525, 55, -0.6, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    buildRoute("C", 2, 530, 50, 0.6, [0, 0, 1, 2, 0, 0, 0, 0, 0, 0, 0]),
  ],
  recommendation: {
    route_id: "B",
    ranking: ["B", "C", "A"],
    reasons: [
      "Beats Route C on High miles: 0.0 mi vs 53.0 mi (tied on No Travel miles, Severe miles)",
      "Beats Route A on Severe miles: 0.0 mi vs 100.0 mi (tied on No Travel miles)",
    ],
    criteria: [
      "Fewest No Travel miles",
      "Fewest Severe miles",
      "Fewest High miles",
      "Lowest average risk",
      "Shortest travel time",
    ],
  },
  warnings: [],
};

export function heatmap(): HeatmapResponse {
  const cols = 12;
  const rows = 8;
  const cells = Array.from({ length: cols * rows }, (_, i) => i);
  const hours = Array.from({ length: 49 }, (_, h) => h);
  const layer = (fn: (cell: number, hour: number) => number) => hours.map((h) => cells.map((c) => fn(c, h)));
  return {
    grid: { cols, rows, west: -112.5, east: -104.5, south: 39.0, north: 41.5, step_deg: 0.67, buffer_mi: 30 },
    cells,
    hours,
    times: hours.map((h) => new Date(Date.parse(DEPARTURE) + h * 3600e3).toISOString()),
    layers: {
      risk: layer((c, h) => ((c + h) % 12 === 0 ? 3 : (c + h) % 5 === 0 ? 1 : 0)),
      wind: layer((c, h) => 10 + ((c * 7 + h * 3) % 40)),
      rain: layer((c, h) => ((c + h) % 9 === 0 ? 0.3 : 0)),
      snow: layer(() => 0),
    },
  };
}

export const geocodeResults: Record<string, typeof ORIGIN[]> = {
  denv: [ORIGIN, { label: "Denver, Bremer, Iowa, US", lat: 42.67, lon: -92.34 }],
  salt: [DESTINATION],
};

/** A blank basemap so tests never depend on the external tile server. */
export const blankStyle = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#eef1f4" } }],
};
