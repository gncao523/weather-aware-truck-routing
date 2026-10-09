export function formatDuration(seconds: number): string {
  const totalMin = Math.round(seconds / 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

const timeFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

export function formatTime(iso: string | number | Date): string {
  return timeFmt.format(new Date(iso));
}

export function formatDateTime(iso: string | number | Date): string {
  return dateTimeFmt.format(new Date(iso));
}

export function formatMiles(mi: number, digits = 0): string {
  return `${mi.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })} mi`;
}

/** Value for an <input type="datetime-local"> in the browser's time zone. */
export function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function nextQuarterHour(from = new Date()): Date {
  const d = new Date(from);
  d.setSeconds(0, 0);
  d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15);
  return d;
}

export const localTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
