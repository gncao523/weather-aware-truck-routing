import { useState } from "react";
import { localTimeZone, nextQuarterHour, toLocalInputValue } from "../lib/format";
import type { Place, TripInput } from "../types";
import { PlaceInput } from "./PlaceInput";

const INTERVALS = [10, 25, 50] as const;

const EXAMPLES: { name: string; origin: Place; destination: Place }[] = [
  {
    name: "Dallas → Chicago",
    origin: { label: "Dallas, Texas, US", lat: 32.7767, lon: -96.797 },
    destination: { label: "Chicago, Illinois, US", lat: 41.8781, lon: -87.6298 },
  },
  {
    name: "Denver → Salt Lake City",
    origin: { label: "Denver, Colorado, US", lat: 39.7392, lon: -104.9903 },
    destination: { label: "Salt Lake City, Utah, US", lat: 40.7608, lon: -111.891 },
  },
  {
    name: "Seattle → Boise",
    origin: { label: "Seattle, Washington, US", lat: 47.6062, lon: -122.3321 },
    destination: { label: "Boise, Idaho, US", lat: 43.615, lon: -116.2023 },
  },
];

interface Props {
  loading: boolean;
  onSubmit: (input: TripInput) => void;
}

export function TripForm({ loading, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextQuarterHour()));
  const [load, setLoad] = useState("36000");
  const [interval, setIntervalMiles] = useState<(typeof INTERVALS)[number]>(25);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const loadLbs = Number(load);
    const dep = new Date(departure);
    if (!origin || !destination) return setError("Pick an origin and a destination from the suggestions.");
    if (Number.isNaN(dep.getTime())) return setError("Enter a valid departure date and time.");
    if (!Number.isFinite(loadLbs) || loadLbs < 0 || loadLbs > 150000)
      return setError("Load weight must be between 0 and 150,000 lb.");
    setError(null);
    onSubmit({ origin, destination, departure: dep.toISOString(), load_lbs: loadLbs, interval_miles: interval });
  };

  const swap = () => {
    setOrigin(destination);
    setDestination(origin);
  };

  return (
    <form className="trip-form" onSubmit={submit} noValidate>
      <div className="od">
        <PlaceInput label="Origin" value={origin} onChange={setOrigin} />
        <button type="button" className="swap" onClick={swap} title="Swap origin and destination" aria-label="Swap">
          ⇅
        </button>
        <PlaceInput label="Destination" value={destination} onChange={setDestination} />
      </div>

      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure ({localTimeZone})</label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            onChange={(e) => setDeparture(e.target.value)}
            required
          />
        </div>
        <div className="field narrow">
          <label htmlFor="load">Load (lb)</label>
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={150000}
            step={500}
            value={load}
            onChange={(e) => setLoad(e.target.value)}
            required
          />
        </div>
      </div>

      <div className="field">
        <span className="label">Weather checkpoint every</span>
        <div className="segmented" role="radiogroup" aria-label="Checkpoint interval">
          {INTERVALS.map((n) => (
            <button
              key={n}
              type="button"
              role="radio"
              aria-checked={interval === n}
              className={interval === n ? "on" : ""}
              onClick={() => setIntervalMiles(n)}
            >
              {n} mi
            </button>
          ))}
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}

      <button className="primary" type="submit" disabled={loading}>
        {loading ? "Planning routes…" : "Find safest route"}
      </button>

      <div className="examples">
        <span>Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.name}
            type="button"
            className="link"
            onClick={() => {
              setOrigin(ex.origin);
              setDestination(ex.destination);
            }}
          >
            {ex.name}
          </button>
        ))}
      </div>
    </form>
  );
}
