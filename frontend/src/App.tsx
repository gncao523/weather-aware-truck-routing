import { useCallback, useMemo, useRef, useState } from "react";
import { fetchHeatmap, planTrip } from "./api";
import { CheckpointTable } from "./components/CheckpointTable";
import { HeatmapControls } from "./components/HeatmapControls";
import { type MapFocus, MapView } from "./components/MapView";
import { RoutePanel } from "./components/RoutePanel";
import { TripForm } from "./components/TripForm";
import { formatMiles } from "./lib/format";
import { HeatmapFrames } from "./lib/heatmapRender";
import { checkpointAtMile, thin, truckPosition } from "./lib/routeGeometry";
import type { HeatMetric, HeatmapResponse, PlanResponse, TripInput } from "./types";

const HEATMAP_LINE_POINTS = 400;
const MAX_HOUR = 48;

type HeatStatus = "idle" | "loading" | "ready" | "error";

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<MapFocus | null>(null);

  const [heat, setHeat] = useState<HeatmapResponse | null>(null);
  const [heatStatus, setHeatStatus] = useState<HeatStatus>("idle");
  const [heatError, setHeatError] = useState<string | null>(null);
  const [heatVisible, setHeatVisible] = useState(true);
  const [metric, setMetric] = useState<HeatMetric>("risk");
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const inflight = useRef<AbortController | null>(null);

  const onSubmit = useCallback(async (input: TripInput) => {
    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setPlanning(true);
    setPlanError(null);
    setPlaying(false);
    setHeat(null);
    setHeatStatus("idle");
    let result: PlanResponse;
    try {
      result = await planTrip(input, ctrl.signal);
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setPlanError((err as Error).message);
      setPlanning(false);
      return;
    }
    setPlan(result);
    setSelectedId(result.recommendation.route_id);
    setHour(0);
    setFocus(null);
    setPlanning(false);

    // The heatmap loads after the routes are on screen; its failure doesn't hide the plan.
    setHeatStatus("loading");
    setHeatError(null);
    try {
      const lines = result.routes.map((r) => thin(r.geometry, HEATMAP_LINE_POINTS));
      const heatmap = await fetchHeatmap(lines, result.request.departure, result.request.load_lbs, ctrl.signal);
      if (ctrl.signal.aborted) return;
      setHeat(heatmap);
      setHeatStatus("ready");
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setHeatError((err as Error).message);
      setHeatStatus("error");
    }
  }, []);

  const frames = useMemo(() => (heat ? new HeatmapFrames(heat) : null), [heat]);
  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null;

  const truck = useMemo(() => (selected ? truckPosition(selected, hour * 3600) : null), [selected, hour]);
  const truckText = useMemo(() => {
    if (!selected || !truck || heatStatus !== "ready") return null;
    if (truck.arrived) return `Route ${selected.id}: arrived at destination`;
    const cp = checkpointAtMile(selected, truck.mile);
    return `Route ${selected.id} truck at ${formatMiles(truck.mile)} — conditions there: ${cp.risk.label}`;
  }, [selected, truck, heatStatus]);

  const advance = useCallback(() => setHour((h) => (h >= MAX_HOUR ? 0 : h + 1)), []);
  const onFocus = useCallback(
    (index: number) => selectedId && setFocus({ routeId: selectedId, index, nonce: Date.now() }),
    [selectedId],
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <h1>Weather-Aware Truck Routing</h1>
          <p>Compare 3 routes using the forecast at your ETA for each checkpoint, plus your load weight.</p>
        </header>

        <TripForm loading={planning} onSubmit={onSubmit} />

        {planError && (
          <div className="error-box" role="alert">
            {planError}
          </div>
        )}

        {plan && selected && (
          <>
            <RoutePanel plan={plan} selectedId={selected.id} onSelect={setSelectedId} />
            <CheckpointTable route={selected} onFocus={onFocus} />
          </>
        )}

        {!plan && !planning && (
          <div className="empty-hint">
            <p>
              Enter a trip to see three route options, weather checkpoints with ETAs, risk levels and a 0–48 h
              weather heatmap along the corridor.
            </p>
          </div>
        )}

        <footer className="credits">
          Routing © OSRM / OpenStreetMap · Weather: Open-Meteo · Search: Photon · Map: OpenFreeMap
        </footer>
      </aside>

      <main className="map-area">
        <MapView
          plan={plan}
          selectedId={selectedId}
          onSelect={setSelectedId}
          frames={frames}
          heatVisible={heatVisible}
          metric={metric}
          hour={hour}
          truck={heatStatus === "ready" && truck && !truck.arrived ? truck.coord : null}
          focus={focus}
        />
        {planning && (
          <div className="map-overlay" role="status">
            <span className="spinner" /> Routing and fetching forecasts at each checkpoint ETA…
          </div>
        )}
        {plan && (
          <HeatmapControls
            status={heatStatus}
            error={heatError}
            times={heat?.times ?? []}
            metric={metric}
            onMetric={setMetric}
            hour={hour}
            onHour={setHour}
            onAdvance={advance}
            playing={playing}
            onPlaying={setPlaying}
            visible={heatVisible}
            onVisible={setHeatVisible}
            truckText={truckText}
          />
        )}
      </main>
    </div>
  );
}
