import { formatTime } from "../lib/format";
import { riskColor } from "../lib/risk";
import type { RouteOption } from "../types";

interface Props {
  route: RouteOption;
  onFocus: (index: number) => void;
}

export function CheckpointTable({ route, onFocus }: Props) {
  return (
    <section className="checkpoints" aria-label={`Route ${route.id} checkpoints`}>
      <h3>
        Route {route.id} checkpoints <span className="muted">({route.checkpoints.length})</span>
      </h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Mile</th>
              <th>ETA</th>
              <th title="Sustained wind (gust), mph">Wind</th>
              <th title="Rain incl. showers, in/hr">Rain</th>
              <th title="Snowfall, in/hr">Snow</th>
              <th>Risk</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((c) => (
              <tr key={c.index} onClick={() => onFocus(c.index)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onFocus(c.index)}>
                <td>{c.mile.toFixed(0)}</td>
                <td>{formatTime(c.eta)}</td>
                <td>
                  {c.weather.wind_mph.toFixed(0)} <span className="muted">({c.weather.gust_mph.toFixed(0)})</span>
                </td>
                <td>{c.weather.rain_in_hr.toFixed(2)}</td>
                <td>{c.weather.snow_in_hr.toFixed(2)}</td>
                <td>
                  <span
                    className="risk-chip"
                    style={{ background: riskColor(c.risk.level) }}
                    title={c.risk.load_rule ?? (c.risk.drivers.length ? `Driven by ${c.risk.drivers.join(", ")}` : "")}
                  >
                    {c.risk.label}
                    {c.risk.load_rule ? " ⚖" : ""}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Wind mph (gust) · rain &amp; snow in/hr · ⚖ = escalated by a load-weight rule. Click a row to show it on the map.</p>
    </section>
  );
}
