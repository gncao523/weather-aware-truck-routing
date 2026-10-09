/** Shapes returned by the Django API (see backend/planner/services/planner.py). */

export type RiskLevel = 0 | 1 | 2 | 3 | 4;
export type LonLat = [number, number];

export interface Place {
  lat: number;
  lon: number;
  label: string;
}

export interface CheckpointWeather {
  wind_mph: number;
  gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  data_gap: boolean;
}

export interface CheckpointRisk {
  level: RiskLevel;
  label: string;
  wind_level: RiskLevel;
  rain_level: RiskLevel;
  snow_level: RiskLevel;
  load_rule: string | null;
  drivers: string[];
}

export interface Checkpoint {
  index: number;
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  eta_offset_s: number;
  span_mi: [number, number];
  weather: CheckpointWeather;
  risk: CheckpointRisk;
}

export interface MilesByLevel {
  low: number;
  moderate: number;
  high: number;
  severe: number;
  no_travel: number;
}

export interface RouteOption {
  id: string;
  kind: "alternative" | "detour";
  distance_mi: number;
  duration_s: number;
  engine_duration_s: number;
  departure: string;
  arrival: string;
  geometry: LonLat[];
  time_offsets_s: number[];
  mile_offsets: number[];
  checkpoints: Checkpoint[];
  summary: {
    miles_by_level: MilesByLevel;
    avg_risk: number;
    max_level: RiskLevel;
    max_label: string;
  };
  rank: number;
}

export interface PlanResponse {
  generated_at: string;
  request: {
    origin: Place;
    destination: Place;
    departure: string;
    load_lbs: number;
    interval_miles: number;
    truck_max_speed_mph: number;
  };
  routes: RouteOption[];
  recommendation: {
    route_id: string;
    ranking: string[];
    reasons: string[];
    criteria: string[];
  };
  warnings: string[];
}

export type HeatMetric = "risk" | "wind" | "rain" | "snow";

export interface HeatmapResponse {
  grid: {
    cols: number;
    rows: number;
    west: number;
    east: number;
    south: number;
    north: number;
    step_deg: number;
    buffer_mi: number;
  };
  /** Flat cell indices (row * cols + col, row 0 = south) inside the corridor. */
  cells: number[];
  hours: number[];
  times: string[];
  /** layers[metric][hour][k] is the value of cells[k] at times[hour]. */
  layers: Record<HeatMetric, number[][]>;
}

export interface TripInput {
  origin: Place;
  destination: Place;
  departure: string; // ISO 8601 with offset
  load_lbs: number;
  interval_miles: 10 | 25 | 50;
}
