import type { Shot } from "./types";

/** Length of a 2-D error, or null when either component is missing. */
export function magnitude(x: number | null, y: number | null): number | null {
  if (x === null || y === null || Number.isNaN(x) || Number.isNaN(y)) return null;
  return Math.hypot(x, y);
}

/** Linear-interpolated percentile of the finite values (q in 0..100); null when there are none. */
export function percentile(values: (number | null)[], q: number): number | null {
  const v = values.filter((x): x is number => x !== null && Number.isFinite(x)).sort((a, b) => a - b);
  if (v.length === 0) return null;
  const pos = ((v.length - 1) * q) / 100;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return v[lo] + (v[hi] - v[lo]) * (pos - lo);
}

/** Seconds into the shift as h:mm. */
export function clock(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}`;
}

export interface ShiftSummary {
  fired: number;
  ffP95: number | null;
  nfP95: number | null;
  withinTolerance: number;
  meanEnergy: number | null;
}

/** What the platform measured over the shift's experiment shots (measured values, not simulation truth). */
export function summarise(shots: Shot[], tol: { nf_mm: number; ff_urad: number }): ShiftSummary {
  const exp = shots.filter((s) => s.purpose === "experiment");
  const ff = exp.map((s) => magnitude(s.ff_x_urad, s.ff_y_urad));
  const nf = exp.map((s) => magnitude(s.nf_x_mm, s.nf_y_mm));
  const within = exp.filter(
    (_, i) =>
      (ff[i] ?? Number.POSITIVE_INFINITY) <= tol.ff_urad && (nf[i] ?? Number.POSITIVE_INFINITY) <= tol.nf_mm,
  );
  const energies = exp.map((s) => s.energy_reported_j).filter((e): e is number => e !== null);
  return {
    fired: exp.length,
    ffP95: percentile(ff, 95),
    nfP95: percentile(nf, 95),
    withinTolerance: within.length,
    meanEnergy: energies.length ? energies.reduce((a, b) => a + b, 0) / energies.length : null,
  };
}

export function fmt(value: number | null | undefined, digits = 1, unit = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}
