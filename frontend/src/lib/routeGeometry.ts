import type { LonLat, RiskLevel, RouteOption } from "../types";

/** Index i such that values[i] <= x <= values[i+1] (values non-decreasing, length >= 2). */
function bracket(values: number[], x: number): number {
  let lo = 0;
  let hi = values.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (values[mid] <= x) lo = mid;
    else hi = mid;
  }
  return lo;
}

function lerp(a: LonLat, b: LonLat, t: number): LonLat {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

/** Point on the line at a given value of a monotonic per-vertex measure (miles or seconds). */
export function pointAtMeasure(coords: LonLat[], measure: number[], x: number): LonLat {
  if (x <= measure[0]) return coords[0];
  const last = measure.length - 1;
  if (x >= measure[last]) return coords[last];
  const i = bracket(measure, x);
  const span = measure[i + 1] - measure[i];
  return lerp(coords[i], coords[i + 1], span > 0 ? (x - measure[i]) / span : 0);
}

/** The part of a line between two measure values, endpoints interpolated. */
export function sliceLine(coords: LonLat[], measure: number[], from: number, to: number): LonLat[] {
  const out: LonLat[] = [pointAtMeasure(coords, measure, from)];
  for (let i = 0; i < coords.length; i++) {
    if (measure[i] > from && measure[i] < to) out.push(coords[i]);
  }
  out.push(pointAtMeasure(coords, measure, to));
  return out;
}

export interface RiskPiece {
  level: RiskLevel;
  coords: LonLat[];
}

/** Splits a route into runs of equal risk, using each checkpoint's mile span. */
export function riskPieces(route: RouteOption): RiskPiece[] {
  const pieces: RiskPiece[] = [];
  let start = 0;
  const cps = route.checkpoints;
  for (let i = 0; i < cps.length; i++) {
    const level = cps[i].risk.level;
    const end = cps[i].span_mi[1];
    const nextLevel = i + 1 < cps.length ? cps[i + 1].risk.level : null;
    if (nextLevel !== level) {
      pieces.push({ level, coords: sliceLine(route.geometry, route.mile_offsets, start, end) });
      start = end;
    }
  }
  return pieces;
}

export interface TruckPosition {
  coord: LonLat;
  mile: number;
  arrived: boolean;
  notDeparted: boolean;
}

/** Where the truck is `secondsAfterDeparture` into the trip, following the route's ETA profile. */
export function truckPosition(route: RouteOption, secondsAfterDeparture: number): TruckPosition {
  const t = route.time_offsets_s;
  const coord = pointAtMeasure(route.geometry, t, secondsAfterDeparture);
  let mile: number;
  if (secondsAfterDeparture <= t[0]) mile = 0;
  else if (secondsAfterDeparture >= t[t.length - 1]) mile = route.mile_offsets[route.mile_offsets.length - 1];
  else {
    const i = bracket(t, secondsAfterDeparture);
    const span = t[i + 1] - t[i];
    const f = span > 0 ? (secondsAfterDeparture - t[i]) / span : 0;
    mile = route.mile_offsets[i] + (route.mile_offsets[i + 1] - route.mile_offsets[i]) * f;
  }
  return {
    coord,
    mile,
    arrived: secondsAfterDeparture >= t[t.length - 1],
    notDeparted: secondsAfterDeparture < 0,
  };
}

/** Checkpoint whose mile span contains `mile`. */
export function checkpointAtMile(route: RouteOption, mile: number) {
  return route.checkpoints.find((c) => mile >= c.span_mi[0] && mile <= c.span_mi[1]) ?? route.checkpoints.at(-1)!;
}

export function bounds(routes: RouteOption[]): [LonLat, LonLat] {
  let w = 180, s = 90, e = -180, n = -90;
  for (const r of routes) {
    for (const [x, y] of r.geometry) {
      if (x < w) w = x;
      if (x > e) e = x;
      if (y < s) s = y;
      if (y > n) n = y;
    }
  }
  return [[w, s], [e, n]];
}

/** Evenly thinned copy of a line (keeps both ends) — used for the heatmap request. */
export function thin(coords: LonLat[], maxPoints: number): LonLat[] {
  if (coords.length <= maxPoints) return coords;
  const step = (coords.length - 1) / (maxPoints - 1);
  return Array.from({ length: maxPoints }, (_, k) => coords[Math.round(k * step)]);
}
