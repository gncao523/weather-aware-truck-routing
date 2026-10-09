import type { HeatmapResponse, LonLat, Place, PlanResponse, TripInput } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit & { signal?: AbortSignal }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Can't reach the server. Check your connection and try again.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(body) ?? `Request failed (${res.status})`);
  return body as T;
}

/** Flattens DRF error payloads ({detail} or {field: [msgs]}) into one sentence. */
function errorMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;
  if (typeof b.detail === "string") return b.detail;
  const parts: string[] = [];
  const walk = (v: unknown, key: string) => {
    if (typeof v === "string") parts.push(key === "non_field_errors" ? v : `${key.replace(/_/g, " ")}: ${v}`);
    else if (Array.isArray(v)) v.forEach((x) => walk(x, key));
    else if (v && typeof v === "object") Object.entries(v).forEach(([k, x]) => walk(x, `${key} ${k}`.trim()));
  };
  Object.entries(b).forEach(([k, v]) => walk(v, k));
  return parts.length ? parts.join(" · ") : null;
}

export function geocode(q: string, signal?: AbortSignal): Promise<Place[]> {
  return request<{ results: Place[] }>(`/geocode/?q=${encodeURIComponent(q)}`, { signal }).then((r) => r.results);
}

export function planTrip(input: TripInput, signal?: AbortSignal): Promise<PlanResponse> {
  return request<PlanResponse>("/plan/", { method: "POST", body: JSON.stringify(input), signal });
}

export function fetchHeatmap(
  routes: LonLat[][],
  departure: string,
  loadLbs: number,
  signal?: AbortSignal,
): Promise<HeatmapResponse> {
  return request<HeatmapResponse>("/heatmap/", {
    method: "POST",
    body: JSON.stringify({ routes, departure, load_lbs: loadLbs }),
    signal,
  });
}
