import { describe, expect, it } from "vitest";
import { clock, fmt, magnitude, percentile, summarise } from "./summaries";
import type { Shot } from "./types";

const shot = (over: Partial<Shot>): Shot => ({
  shot_id: "S003-00001",
  day: 3,
  t_s: 0,
  purpose: "experiment",
  pump: 0.8,
  energy_target_j: 10,
  energy_reported_j: 10,
  nf_x_mm: 0,
  nf_y_mm: 0,
  ff_x_urad: 0,
  ff_y_urad: 0,
  peak_fraction: 0.0004,
  fluence_est_j_cm2: 1.6,
  predicted_fluence_j_cm2: 1.6,
  saturated: 0,
  calibrations: {},
  ...over,
});

describe("summaries", () => {
  it("measures 2-D errors and refuses missing ones", () => {
    expect(magnitude(3, 4)).toBe(5);
    expect(magnitude(null, 4)).toBeNull();
  });

  it("interpolates percentiles over finite values", () => {
    expect(percentile([1, 2, 3, 4, 5], 50)).toBe(3);
    expect(percentile([0, 10], 95)).toBeCloseTo(9.5);
    expect(percentile([null, Number.NaN], 50)).toBeNull();
  });

  it("formats time into the shift", () => {
    expect(clock(3 * 3600 + 7 * 60 + 30)).toBe("3:07");
  });

  it("summarises only experiment shots against the tolerance", () => {
    const s = summarise(
      [
        shot({ ff_x_urad: 3, ff_y_urad: 4 }),
        shot({ ff_x_urad: 6, ff_y_urad: 8 }),
        shot({ purpose: "calibration" }),
      ],
      { nf_mm: 0.75, ff_urad: 5 },
    );
    expect(s.fired).toBe(2);
    expect(s.withinTolerance).toBe(1);
    expect(s.meanEnergy).toBe(10);
  });

  it("formats missing numbers as n/a", () => {
    expect(fmt(null)).toBe("n/a");
    expect(fmt(1.234, 2, "J")).toBe("1.23 J");
  });
});
