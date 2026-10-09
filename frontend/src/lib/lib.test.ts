import { describe, expect, it } from "vitest";
import type { Checkpoint, HeatmapResponse, LonLat, RiskLevel, RouteOption } from "../types";
import { cellColor, paintPixels } from "./heatmapRender";
import { pointAtMeasure, riskPieces, sliceLine, thin, truckPosition } from "./routeGeometry";

const line: LonLat[] = [
  [0, 0],
  [1, 0],
  [2, 0],
  [3, 0],
];
const miles = [0, 10, 20, 30];

function cp(index: number, mile: number, span: [number, number], level: RiskLevel): Checkpoint {
  return {
    index,
    mile,
    lat: 0,
    lon: mile / 10,
    eta: "",
    eta_offset_s: mile * 60,
    span_mi: span,
    weather: { wind_mph: 0, gust_mph: 0, rain_in_hr: 0, snow_in_hr: 0, data_gap: false },
    risk: { level, label: "", wind_level: 0, rain_level: 0, snow_level: 0, load_rule: null, drivers: [] },
  };
}

const route = {
  id: "A",
  geometry: line,
  mile_offsets: miles,
  time_offsets_s: [0, 600, 1200, 1800],
  distance_mi: 30,
  checkpoints: [cp(0, 0, [0, 5], 0), cp(1, 10, [5, 15], 0), cp(2, 20, [15, 25], 3), cp(3, 30, [25, 30], 0)],
} as unknown as RouteOption;

describe("route geometry", () => {
  it("interpolates along a measure", () => {
    expect(pointAtMeasure(line, miles, 15)).toEqual([1.5, 0]);
    expect(pointAtMeasure(line, miles, -5)).toEqual([0, 0]);
    expect(pointAtMeasure(line, miles, 99)).toEqual([3, 0]);
  });

  it("slices with interpolated ends", () => {
    expect(sliceLine(line, miles, 5, 25)).toEqual([
      [0.5, 0],
      [1, 0],
      [2, 0],
      [2.5, 0],
    ]);
  });

  it("merges equal-risk checkpoint spans into pieces covering the route", () => {
    const pieces = riskPieces(route);
    expect(pieces.map((p) => p.level)).toEqual([0, 3, 0]);
    expect(pieces[1].coords[0]).toEqual([1.5, 0]);
    expect(pieces[1].coords.at(-1)).toEqual([2.5, 0]);
  });

  it("places the truck by ETA profile", () => {
    const p = truckPosition(route, 900);
    expect(p.coord).toEqual([1.5, 0]);
    expect(p.mile).toBe(15);
    expect(truckPosition(route, 5000).arrived).toBe(true);
  });

  it("thins long lines keeping endpoints", () => {
    const long: LonLat[] = Array.from({ length: 1000 }, (_, i) => [i, 0]);
    const t = thin(long, 50);
    expect(t).toHaveLength(50);
    expect(t[0]).toEqual([0, 0]);
    expect(t.at(-1)).toEqual([999, 0]);
  });
});

describe("heatmap colours", () => {
  it("bands wind by the assessment thresholds", () => {
    const band = (v: number) => cellColor("wind", v).slice(0, 3).join(",");
    expect(band(34.9)).toBe(band(25)); // Moderate
    expect(band(35)).not.toBe(band(34.9)); // High starts at 35
    expect(band(55)).not.toBe(band(54.9)); // No Travel at ≥55
  });

  it("treats exactly 1.00 in/hr rain as Severe, not No Travel", () => {
    expect(cellColor("rain", 1.0)).toEqual(cellColor("rain", 0.5));
    expect(cellColor("rain", 1.01)).not.toEqual(cellColor("rain", 1.0));
  });

  it("leaves calm cells transparent", () => {
    expect(cellColor("wind", 2)[3]).toBe(0);
  });

  it("paints cells into the right pixel (row 0 = south)", () => {
    const data = {
      grid: { cols: 2, rows: 2, west: 0, east: 2, south: 0, north: 2, step_deg: 1, buffer_mi: 30 },
      cells: [1], // col 1, row 0 → bottom-right pixel
      hours: [0],
      times: [""],
      layers: { risk: [[4]], wind: [[0]], rain: [[0]], snow: [[0]] },
    } as HeatmapResponse;
    const px = paintPixels(data, "risk", 0);
    const bottomRight = ((2 - 1 - 0) * 2 + 1) * 4;
    expect(px[bottomRight + 3]).toBeGreaterThan(0);
    expect(px[3]).toBe(0);
  });
});
