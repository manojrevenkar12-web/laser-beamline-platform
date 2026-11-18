export interface Shot {
  shot_id: string;
  day: number;
  t_s: number;
  purpose: "experiment" | "calibration";
  pump: number;
  energy_target_j: number;
  energy_reported_j: number | null;
  nf_x_mm: number | null;
  nf_y_mm: number | null;
  ff_x_urad: number | null;
  ff_y_urad: number | null;
  peak_fraction: number | null;
  fluence_est_j_cm2: number | null;
  predicted_fluence_j_cm2: number | null;
  saturated: number;
  calibrations: Record<string, string | null>;
}

export interface Held {
  decision_id: string;
  t_s: number;
  reasons: string[];
  warnings: string[];
  predicted: number | null;
  limit: number | null;
  action: string;
}

export interface Alignment {
  reason: string;
  started_s: number;
  seconds: number;
  iterations: number;
  converged: boolean;
  final_error: number[];
  refreshed: boolean;
  fault: string;
}

export interface Frame {
  src: string;
  size: number;
  cx: number;
  cy: number;
  d4x: number;
  d4y: number;
  peak_fraction: number;
  saturated: number;
}

export interface Device {
  name: string;
  ok: number;
  failures: number;
  crc_errors: number;
  faulted: boolean;
  last_error: string;
}

export interface EnergyCal {
  cal_id: string;
  day: number;
  factor: number;
  u_k2: number;
  n: number;
  applied: boolean;
  reason: string;
  change: number;
}

export interface ShiftData {
  beamline: string;
  day: number;
  engine: string;
  tolerance: { nf_mm: number; ff_urad: number; energy_rel: number };
  reference: { nf_px: number[]; ff_px: number[]; nf_mm_per_px: number; ff_urad_per_px: number };
  shots: Shot[];
  held: Held[];
  alignments: Alignment[];
  alerts: { t_s: number; severity: string; kind: string; message: string }[];
  matrix: {
    cal_id: string;
    matrix: number[][];
    backlash: number[];
    reverse_ratio: number[];
    condition: number;
  };
  energy_cals: EnergyCal[];
  devices: Device[];
  frames: Partial<Record<"nf" | "ff", Frame>>;
  last_shot: string;
  log: { fired: number; blocked: number; alignments: number; align_minutes: number; inspections: number };
}

export interface Stat {
  mean: number | null;
  sd: number | null;
  min: number | null;
  max: number | null;
  n: number;
}

export interface DesignSummary {
  description: string;
  summary: Record<string, Stat>;
}

export interface Campaign {
  days: number;
  seeds: number[];
  commit: string;
  gates: { gate: string; value: number; rule: { min?: number; max?: number }; pass: boolean }[];
  designs: Record<string, DesignSummary>;
}

export interface EvaluationData {
  dev?: Campaign;
  heldout?: Campaign;
}
