import { useEffect } from "react";
import { formatDateTime } from "../lib/format";
import { METRIC_INFO, RISK_COLORS, RISK_LABELS } from "../lib/risk";
import type { HeatMetric } from "../types";

const METRICS: HeatMetric[] = ["risk", "wind", "rain", "snow"];
const MAX_HOUR = 48;
const PLAY_STEP_MS = 400;

/** Band labels exactly as written in the assessment's risk table. */
const BAND_LABELS: Record<Exclude<HeatMetric, "risk">, string[]> = {
  wind: ["<25", "25–34", "35–44", "45–54", "≥55"],
  rain: ["<0.10", "0.10–0.25", "0.25–0.50", "0.50–1.00", ">1.00"],
  snow: ["<0.5", "0.5–1.0", "1.0–2.0", "2.0–3.0", ">3.0"],
};

interface Props {
  status: "idle" | "loading" | "ready" | "error";
  error: string | null;
  times: string[];
  metric: HeatMetric;
  onMetric: (m: HeatMetric) => void;
  hour: number;
  onHour: (h: number) => void;
  /** Called on every playback tick; the parent advances (and wraps) the hour. */
  onAdvance: () => void;
  playing: boolean;
  onPlaying: (p: boolean) => void;
  visible: boolean;
  onVisible: (v: boolean) => void;
  truckText: string | null;
}

export function HeatmapControls(p: Props) {
  const { playing, onHour, onAdvance, onPlaying, hour } = p;

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(onAdvance, PLAY_STEP_MS);
    return () => window.clearInterval(id);
  }, [playing, onAdvance]);

  const disabled = p.status !== "ready";
  const time = p.times[hour];

  return (
    <div className="heat-controls" aria-label="Weather heatmap controls">
      <div className="heat-row">
        <label className="toggle">
          <input type="checkbox" checked={p.visible} onChange={(e) => p.onVisible(e.target.checked)} />
          Heatmap
        </label>
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {METRICS.map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={p.metric === m}
              className={p.metric === m ? "on" : ""}
              onClick={() => p.onMetric(m)}
            >
              {METRIC_INFO[m].label}
            </button>
          ))}
        </div>
        <span className="heat-status">
          {p.status === "loading" && "Loading corridor forecast…"}
          {p.status === "error" && <span className="err">{p.error}</span>}
        </span>
      </div>

      <div className="heat-row">
        <button
          type="button"
          className="play"
          disabled={disabled}
          onClick={() => onPlaying(!playing)}
          aria-label={playing ? "Pause" : "Play forecast"}
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          className="slider"
          type="range"
          min={0}
          max={MAX_HOUR}
          step={1}
          value={hour}
          disabled={disabled}
          onChange={(e) => {
            onPlaying(false);
            onHour(Number(e.target.value));
          }}
          aria-label="Forecast hour after departure"
          aria-valuetext={time ? `+${hour} hours, ${formatDateTime(time)}` : `+${hour} hours`}
        />
        <span className="hour-label">
          <b>+{hour}h</b>
          {time && <span className="muted"> {formatDateTime(time)}</span>}
        </span>
      </div>

      <div className="heat-row legend-row">
        <Legend metric={p.metric} />
        {p.truckText && <span className="truck-text">🚚 {p.truckText}</span>}
      </div>
    </div>
  );
}

function Legend({ metric }: { metric: HeatMetric }) {
  if (metric === "risk") {
    return (
      <div className="legend">
        {RISK_LABELS.map((l, i) => (
          <span key={l}>
            <i style={{ background: RISK_COLORS[i] }} />
            {l}
          </span>
        ))}
      </div>
    );
  }
  const labels = BAND_LABELS[metric];
  const unit = METRIC_INFO[metric].unit;
  return (
    <div className="legend">
      {labels.map((l, i) => (
        <span key={l}>
          <i style={{ background: RISK_COLORS[i] }} />
          {l}
        </span>
      ))}
      <span className="muted">{unit}</span>
    </div>
  );
}
