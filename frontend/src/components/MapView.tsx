import maplibregl, { type ExpressionSpecification, type GeoJSONSource, type ImageSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import { formatDuration, formatMiles, formatTime } from "../lib/format";
import type { HeatmapFrames } from "../lib/heatmapRender";
import { RISK_COLORS, riskColor } from "../lib/risk";
import { bounds, pointAtMeasure, riskPieces } from "../lib/routeGeometry";
import type { Checkpoint, HeatMetric, LonLat, PlanResponse, RouteOption } from "../types";

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const BLANK_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
const LABEL_POSITIONS = [0.5, 0.33, 0.67];

export interface MapFocus {
  routeId: string;
  index: number;
  nonce: number;
}

interface Props {
  plan: PlanResponse | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  frames: HeatmapFrames | null;
  heatVisible: boolean;
  metric: HeatMetric;
  hour: number;
  truck: LonLat | null;
  focus: MapFocus | null;
}

const riskColorExpr: ExpressionSpecification = [
  "match",
  ["get", "level"],
  0, RISK_COLORS[0],
  1, RISK_COLORS[1],
  2, RISK_COLORS[2],
  3, RISK_COLORS[3],
  RISK_COLORS[4],
];

function isSelected(id: string | null): ExpressionSpecification {
  return ["==", ["get", "route"], id ?? ""];
}

function checkpointHtml(route: RouteOption, c: Checkpoint): string {
  const w = c.weather;
  const r = c.risk;
  return `
    <div class="cp-popup">
      <div class="cp-title"><span class="route-badge sm">${route.id}</span> Mile ${c.mile.toFixed(0)}
        <span class="risk-chip" style="background:${riskColor(r.level)}">${r.label}</span></div>
      <div class="cp-eta">ETA ${formatTime(c.eta)} · +${formatDuration(c.eta_offset_s)}</div>
      <table>
        <tr><td>Wind</td><td>${w.wind_mph.toFixed(0)} mph <span class="muted">(gust ${w.gust_mph.toFixed(0)})</span></td><td>${dot(r.wind_level)}</td></tr>
        <tr><td>Rain</td><td>${w.rain_in_hr.toFixed(2)} in/hr</td><td>${dot(r.rain_level)}</td></tr>
        <tr><td>Snow</td><td>${w.snow_in_hr.toFixed(2)} in/hr</td><td>${dot(r.snow_level)}</td></tr>
      </table>
      ${r.load_rule ? `<div class="cp-rule">⚖ ${r.load_rule}</div>` : ""}
      ${w.data_gap ? `<div class="cp-rule">Forecast data incomplete here</div>` : ""}
      <div class="muted small">Covers miles ${c.span_mi[0].toFixed(0)}–${c.span_mi[1].toFixed(0)}</div>
    </div>`;
}

function dot(level: number): string {
  return `<span class="dot" style="background:${riskColor(level)}"></span>`;
}

function labelHtml(route: RouteOption, recommended: boolean): string {
  const m = route.summary.miles_by_level;
  return `
    <div class="rl-head"><span class="route-badge sm">${route.id}</span>${recommended ? '<span class="rl-star">★</span>' : ""}
      <b>${formatDuration(route.duration_s)}</b> · ${formatMiles(route.distance_mi)}</div>
    <div class="rl-body">Arrive ${formatTime(route.arrival)} · Max <b style="color:${riskColor(route.summary.max_level)}">${route.summary.max_label}</b></div>
    <div class="rl-body">Severe ${m.severe.toFixed(0)} mi · High ${m.high.toFixed(0)} mi</div>`;
}

export function MapView({ plan, selectedId, onSelect, frames, heatVisible, metric, hour, truck, focus }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const planRef = useRef(plan);
  const onSelectRef = useRef(onSelect);
  const labelMarkers = useRef<Map<string, maplibregl.Marker>>(new Map());
  const endpointMarkers = useRef<maplibregl.Marker[]>([]);
  const truckMarker = useRef<maplibregl.Marker | null>(null);
  const pinnedPopup = useRef<maplibregl.Popup | null>(null);
  planRef.current = plan;
  onSelectRef.current = onSelect;

  // --- Map setup (once) ---------------------------------------------------------
  useEffect(() => {
    const map = new maplibregl.Map({
      container: container.current!,
      style: STYLE_URL,
      center: [-96, 38.5],
      zoom: 3.4,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");

    map.on("load", () => {
      const firstSymbol = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
      map.addSource("heat", {
        type: "image",
        url: BLANK_PNG,
        coordinates: [[-1, 1], [1, 1], [1, -1], [-1, -1]],
      });
      map.addLayer(
        {
          id: "heat",
          type: "raster",
          source: "heat",
          layout: { visibility: "none" },
          paint: { "raster-opacity": 0.85, "raster-resampling": "linear", "raster-fade-duration": 0 },
        },
        firstSymbol,
      );

      map.addSource("routes", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: "routes",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#ffffff", "line-width": 6 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "routes",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": riskColorExpr, "line-width": 3.5 },
      });

      map.addSource("checkpoints", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "checkpoints",
        type: "circle",
        source: "checkpoints",
        paint: {
          "circle-color": riskColorExpr,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
          "circle-radius": 4,
        },
      });

      const hover = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "280px" });
      map.on("mousemove", "checkpoints", (e) => {
        const f = e.features?.[0];
        const p = planRef.current;
        if (!f || !p) return;
        const route = p.routes.find((r) => r.id === f.properties.route);
        const cp = route?.checkpoints[f.properties.idx as number];
        if (!route || !cp) return;
        map.getCanvas().style.cursor = "pointer";
        hover.setLngLat([cp.lon, cp.lat]).setHTML(checkpointHtml(route, cp)).addTo(map);
      });
      map.on("mouseleave", "checkpoints", () => {
        map.getCanvas().style.cursor = "";
        hover.remove();
      });
      const selectFromFeature = (e: maplibregl.MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties.route;
        if (id) onSelectRef.current(id);
      };
      map.on("click", "route-line", selectFromFeature);
      map.on("click", "checkpoints", selectFromFeature);
      map.on("mouseenter", "route-line", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "route-line", () => (map.getCanvas().style.cursor = ""));
      setReady(true);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // --- New plan: route geometry, checkpoints, labels, endpoints -------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    labelMarkers.current.forEach((m) => m.remove());
    labelMarkers.current.clear();
    endpointMarkers.current.forEach((m) => m.remove());
    endpointMarkers.current = [];
    pinnedPopup.current?.remove();

    const routeFeatures: GeoJSON.Feature[] = [];
    const cpFeatures: GeoJSON.Feature[] = [];
    for (const r of plan?.routes ?? []) {
      for (const piece of riskPieces(r)) {
        routeFeatures.push({
          type: "Feature",
          properties: { route: r.id, level: piece.level },
          geometry: { type: "LineString", coordinates: piece.coords },
        });
      }
      for (const c of r.checkpoints) {
        cpFeatures.push({
          type: "Feature",
          properties: { route: r.id, idx: c.index, level: c.risk.level },
          geometry: { type: "Point", coordinates: [c.lon, c.lat] },
        });
      }
    }
    (map.getSource("routes") as GeoJSONSource).setData({ type: "FeatureCollection", features: routeFeatures });
    (map.getSource("checkpoints") as GeoJSONSource).setData({ type: "FeatureCollection", features: cpFeatures });

    if (!plan) return;
    plan.routes.forEach((r, i) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "route-label";
      el.innerHTML = labelHtml(r, r.id === plan.recommendation.route_id);
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        onSelectRef.current(r.id);
      });
      const at = pointAtMeasure(r.geometry, r.mile_offsets, r.distance_mi * LABEL_POSITIONS[i % 3]);
      labelMarkers.current.set(r.id, new maplibregl.Marker({ element: el, anchor: "bottom", offset: [0, -8] }).setLngLat(at).addTo(map));
    });

    const { origin, destination } = plan.request;
    endpointMarkers.current = [
      new maplibregl.Marker({ color: "#0b3d4f" }).setLngLat([origin.lon, origin.lat]).setPopup(new maplibregl.Popup({ offset: 24 }).setText(`Origin: ${origin.label}`)).addTo(map),
      new maplibregl.Marker({ color: "#c2255c" }).setLngLat([destination.lon, destination.lat]).setPopup(new maplibregl.Popup({ offset: 24 }).setText(`Destination: ${destination.label}`)).addTo(map),
    ];

    const narrow = map.getContainer().clientWidth < 700;
    map.fitBounds(bounds(plan.routes), {
      padding: narrow ? { top: 60, bottom: 150, left: 30, right: 30 } : { top: 90, bottom: 190, left: 70, right: 70 },
      duration: 900,
    });
  }, [ready, plan]);

  // --- Selection styling ------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const sel = isSelected(selectedId);
    map.setPaintProperty("route-casing", "line-width", ["case", sel, 10, 6]);
    map.setPaintProperty("route-casing", "line-color", ["case", sel, "#0b3d4f", "#ffffff"]);
    map.setPaintProperty("route-line", "line-width", ["case", sel, 6, 3.5]);
    map.setPaintProperty("route-line", "line-opacity", ["case", sel, 1, 0.55]);
    map.setLayoutProperty("route-casing", "line-sort-key", ["case", sel, 1, 0]);
    map.setLayoutProperty("route-line", "line-sort-key", ["case", sel, 1, 0]);
    map.setLayoutProperty("checkpoints", "circle-sort-key", ["case", sel, 1, 0]);
    map.setPaintProperty("checkpoints", "circle-radius", [
      "interpolate", ["linear"], ["zoom"],
      4, ["case", sel, 4, 2.5],
      10, ["case", sel, 8, 4.5],
    ]);
    map.setPaintProperty("checkpoints", "circle-opacity", ["case", sel, 1, 0.6]);
    map.setPaintProperty("checkpoints", "circle-stroke-opacity", ["case", sel, 1, 0.6]);
    labelMarkers.current.forEach((m, id) => {
      m.getElement().classList.toggle("selected", id === selectedId);
      m.getElement().style.zIndex = id === selectedId ? "3" : "2";
    });
  }, [ready, selectedId, plan]);

  // --- Heatmap frame ------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const show = Boolean(frames && heatVisible);
    if (frames && show) {
      (map.getSource("heat") as ImageSource).updateImage({ url: frames.frame(metric, hour), coordinates: frames.coordinates });
    }
    map.setLayoutProperty("heat", "visibility", show ? "visible" : "none");
  }, [ready, frames, heatVisible, metric, hour]);

  // --- Truck position at the slider time ----------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (!truck) {
      truckMarker.current?.remove();
      truckMarker.current = null;
      return;
    }
    if (!truckMarker.current) {
      const el = document.createElement("div");
      el.className = "truck-marker";
      el.title = "Truck position at the selected forecast hour";
      el.innerHTML =
        '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M2 6h11v9H2zM13 9h4l3 3v3h-7z" fill="#fff"/><circle cx="6" cy="17" r="2" fill="#fff"/><circle cx="17" cy="17" r="2" fill="#fff"/></svg>';
      truckMarker.current = new maplibregl.Marker({ element: el }).setLngLat(truck).addTo(map);
    } else {
      truckMarker.current.setLngLat(truck);
    }
  }, [ready, truck]);

  // --- Focus a checkpoint (from the table) ---------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus || !plan) return;
    const route = plan.routes.find((r) => r.id === focus.routeId);
    const cp = route?.checkpoints[focus.index];
    if (!route || !cp) return;
    map.flyTo({ center: [cp.lon, cp.lat], zoom: Math.max(map.getZoom(), 7.5), duration: 700 });
    pinnedPopup.current?.remove();
    pinnedPopup.current = new maplibregl.Popup({ offset: 10, maxWidth: "280px" })
      .setLngLat([cp.lon, cp.lat])
      .setHTML(checkpointHtml(route, cp))
      .addTo(map);
  }, [ready, focus, plan]);

  return <div ref={container} className="map" aria-label="Route map" />;
}
