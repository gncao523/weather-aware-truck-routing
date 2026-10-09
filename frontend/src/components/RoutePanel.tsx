import { formatDuration, formatMiles, formatTime } from "../lib/format";
import { RISK_COLORS, RISK_KEYS, RISK_LABELS, riskColor } from "../lib/risk";
import type { PlanResponse, RouteOption } from "../types";

interface Props {
  plan: PlanResponse;
  selectedId: string;
  onSelect: (id: string) => void;
}

export function RoutePanel({ plan, selectedId, onSelect }: Props) {
  const recommended = plan.recommendation.route_id;
  const ordered = plan.recommendation.ranking.map((id) => plan.routes.find((r) => r.id === id)!);

  return (
    <section className="route-panel" aria-label="Route options">
      <div className="recommendation">
        <div className="rec-head">
          <span className="star" aria-hidden>
            ★
          </span>
          <strong>Recommended: Route {recommended}</strong>
        </div>
        <ul>
          {plan.recommendation.reasons.map((r) => (
            <li key={r} className={r.startsWith("Warning") || r.startsWith("Caution") ? "warn" : ""}>
              {r}
            </li>
          ))}
        </ul>
        <details>
          <summary>How routes are ranked</summary>
          <ol>
            {plan.recommendation.criteria.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ol>
          <p className="muted small">
            Each checkpoint represents the miles closest to it. Average risk is mile-weighted (Low 0 … No Travel 4).
            ETAs use the routing engine's times with trucks capped at {plan.request.truck_max_speed_mph} mph.
          </p>
        </details>
      </div>

      {plan.warnings.length > 0 && (
        <ul className="warnings">
          {plan.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <div className="route-cards">
        {ordered.map((r) => (
          <RouteCard
            key={r.id}
            route={r}
            recommended={r.id === recommended}
            selected={r.id === selectedId}
            onSelect={() => onSelect(r.id)}
          />
        ))}
      </div>
    </section>
  );
}

function RouteCard({
  route,
  recommended,
  selected,
  onSelect,
}: {
  route: RouteOption;
  recommended: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const m = route.summary.miles_by_level;
  const total = route.distance_mi || 1;
  return (
    <button
      type="button"
      className={`route-card${selected ? " selected" : ""}${recommended ? " recommended" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <div className="card-head">
        <span className="route-badge">{route.id}</span>
        <span className="rank">#{route.rank}</span>
        {recommended && <span className="pill rec">★ Recommended</span>}
        {route.summary.max_level >= 4 && <span className="pill nt">No Travel segment</span>}
        <span className="pill" style={{ marginLeft: "auto", background: riskColor(route.summary.max_level), color: "#fff" }}>
          Max {route.summary.max_label}
        </span>
      </div>

      <div className="card-stats">
        <div>
          <span className="stat">{formatDuration(route.duration_s)}</span>
          <span className="stat-label">drive time</span>
        </div>
        <div>
          <span className="stat">{formatMiles(route.distance_mi)}</span>
          <span className="stat-label">distance</span>
        </div>
        <div>
          <span className="stat">{formatTime(route.arrival)}</span>
          <span className="stat-label">arrival</span>
        </div>
      </div>

      <div className="risk-bar" aria-label="Miles by risk level">
        {RISK_KEYS.map((k, i) =>
          m[k] > 0 ? (
            <span
              key={k}
              style={{ width: `${(m[k] / total) * 100}%`, background: RISK_COLORS[i] }}
              title={`${RISK_LABELS[i]}: ${m[k].toFixed(1)} mi`}
            />
          ) : null,
        )}
      </div>

      <dl className="risk-miles">
        <div>
          <dt>Severe</dt>
          <dd>{formatMiles(m.severe, 1)}</dd>
        </div>
        <div>
          <dt>High</dt>
          <dd>{formatMiles(m.high, 1)}</dd>
        </div>
        <div>
          <dt>Avg risk</dt>
          <dd>{route.summary.avg_risk.toFixed(2)}</dd>
        </div>
        <div>
          <dt>No Travel</dt>
          <dd>{formatMiles(m.no_travel, 1)}</dd>
        </div>
      </dl>
    </button>
  );
}
