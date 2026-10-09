import type { HeatMetric, RiskLevel } from "../types";

export const RISK_LABELS = ["Low", "Moderate", "High", "Severe", "No Travel"] as const;
export const RISK_COLORS = ["#2f9e44", "#f2b705", "#f76707", "#e03131", "#862e9c"] as const;
export const RISK_KEYS = ["low", "moderate", "high", "severe", "no_travel"] as const;

export function riskColor(level: RiskLevel | number): string {
  return RISK_COLORS[Math.max(0, Math.min(4, level))];
}

/** Lower bounds of Moderate / High / Severe / No Travel for each measured metric (assessment table). */
export const METRIC_THRESHOLDS: Record<Exclude<HeatMetric, "risk">, readonly number[]> = {
  wind: [25, 35, 45, 55],
  rain: [0.1, 0.25, 0.5, 1.0],
  snow: [0.5, 1.0, 2.0, 3.0],
};

export const METRIC_INFO: Record<HeatMetric, { label: string; unit: string }> = {
  risk: { label: "Risk", unit: "" },
  wind: { label: "Wind", unit: "mph" },
  rain: { label: "Rain", unit: "in/hr" },
  snow: { label: "Snow", unit: "in/hr" },
};
