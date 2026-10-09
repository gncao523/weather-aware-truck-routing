import { useEffect, useId, useRef, useState } from "react";
import { geocode } from "../api";
import type { Place } from "../types";

interface Props {
  label: string;
  value: Place | null;
  onChange: (place: Place | null) => void;
  placeholder?: string;
}

/** Search-as-you-type place picker (debounced, keyboard accessible). */
export function PlaceInput({ label, value, onChange, placeholder }: Props) {
  const id = useId();
  const [text, setText] = useState(value?.label ?? "");
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const typed = useRef(false);

  useEffect(() => {
    setText(value?.label ?? "");
  }, [value]);

  useEffect(() => {
    if (!typed.current) return;
    const q = text.trim();
    if (q.length < 3) {
      setResults([]);
      return;
    }
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      geocode(q, ctrl.signal)
        .then((r) => {
          setResults(r);
          setActive(0);
          setOpen(true);
          setError(null);
        })
        .catch((e: Error) => e.name !== "AbortError" && setError(e.message))
        .finally(() => setLoading(false));
    }, 300);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [text]);

  const choose = (p: Place) => {
    typed.current = false;
    onChange(p);
    setText(p.label);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || !results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="field place-input">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        placeholder={placeholder ?? "City, address or lat, lon"}
        value={text}
        onChange={(e) => {
          typed.current = true;
          setText(e.target.value);
          if (value) onChange(null);
        }}
        onKeyDown={onKeyDown}
        onFocus={() => results.length && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
      />
      {loading && <span className="input-spinner" aria-hidden />}
      {open && results.length > 0 && (
        <ul className="suggestions" id={`${id}-list`} role="listbox">
          {results.map((r, i) => (
            <li
              key={`${r.lat},${r.lon},${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(r);
              }}
              onMouseEnter={() => setActive(i)}
            >
              {r.label}
            </li>
          ))}
        </ul>
      )}
      {open && !loading && results.length === 0 && text.trim().length >= 3 && (
        <ul className="suggestions">
          <li className="muted">No matches</li>
        </ul>
      )}
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}
