import type { HeatMetric, HeatmapResponse } from "../types";
import { METRIC_THRESHOLDS, RISK_COLORS } from "./risk";

type RGBA = [number, number, number, number];

function hex(color: string, alpha: number): RGBA {
  const n = parseInt(color.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, Math.round(alpha * 255)];
}

const RISK_ALPHA = [0.14, 0.5, 0.58, 0.66, 0.74];
const RISK_RGBA: RGBA[] = RISK_COLORS.map((c, i) => hex(c, RISK_ALPHA[i]));
const TRANSPARENT: RGBA = [0, 0, 0, 0];

/**
 * Colour for one cell. Risk uses its level colour. Wind/rain/snow are banded by
 * the assessment thresholds so a colour always means the same risk band as in
 * the rules table; the Low band fades in from transparent as the value rises.
 */
export function cellColor(metric: HeatMetric, value: number): RGBA {
  if (metric === "risk") return RISK_RGBA[Math.max(0, Math.min(4, Math.round(value)))];
  const t = METRIC_THRESHOLDS[metric];
  for (let band = 4; band >= 1; band--) {
    const atOrAbove = band === 4 && metric !== "wind" ? value > t[3] : value >= t[band - 1];
    if (atOrAbove) return RISK_RGBA[band];
  }
  const f = value / t[0];
  if (f < 0.25) return TRANSPARENT;
  const [r, g, b] = RISK_RGBA[0];
  return [r, g, b, Math.round(255 * 0.3 * Math.min(1, (f - 0.25) / 0.75))];
}

/** Paints one hour of one layer as a cols×rows RGBA buffer (row 0 = north). */
export function paintPixels(data: HeatmapResponse, metric: HeatMetric, hour: number): Uint8ClampedArray {
  const { cols, rows } = data.grid;
  const px = new Uint8ClampedArray(cols * rows * 4);
  const values = data.layers[metric][hour];
  for (let k = 0; k < data.cells.length; k++) {
    const idx = data.cells[k];
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const o = ((rows - 1 - row) * cols + col) * 4;
    const c = cellColor(metric, values[k]);
    px[o] = c[0];
    px[o + 1] = c[1];
    px[o + 2] = c[2];
    px[o + 3] = c[3];
  }
  return px;
}

/**
 * Renders (and memoises) PNG data URLs. Each frame is tiny (one pixel per grid
 * cell); MapLibre stretches it over the corridor with linear filtering, which is
 * what makes the heatmap smooth while the slider moves.
 */
export class HeatmapFrames {
  private cache = new Map<string, string>();
  private canvas = document.createElement("canvas");

  constructor(private data: HeatmapResponse) {
    this.canvas.width = data.grid.cols;
    this.canvas.height = data.grid.rows;
  }

  frame(metric: HeatMetric, hour: number): string {
    const key = `${metric}:${hour}`;
    let url = this.cache.get(key);
    if (!url) {
      const ctx = this.canvas.getContext("2d")!;
      const { cols, rows } = this.data.grid;
      ctx.putImageData(new ImageData(paintPixels(this.data, metric, hour), cols, rows), 0, 0);
      url = this.canvas.toDataURL("image/png");
      this.cache.set(key, url);
    }
    return url;
  }

  /** Image corners in MapLibre order: top-left, top-right, bottom-right, bottom-left. */
  get coordinates(): [[number, number], [number, number], [number, number], [number, number]] {
    const { west, east, north, south } = this.data.grid;
    return [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ];
  }
}
