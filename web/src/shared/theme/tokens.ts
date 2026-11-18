// The same tokens for SVG drawing, where CSS variables are read at render time.
export const color = {
  paper: "var(--paper)",
  panel: "var(--panel)",
  ink: "var(--ink)",
  muted: "var(--muted)",
  rule: "var(--rule)",
  ruleStrong: "var(--rule-strong)",
  beam: "var(--beam)",
  beamSoft: "var(--beam-soft)",
  permit: "var(--permit)",
  permitSoft: "var(--permit-soft)",
  hold: "var(--hold)",
  holdSoft: "var(--hold-soft)",
  calib: "var(--calib)",
} as const;

export const motion = {
  reveal: { duration: 0.5, ease: [0.2, 0.7, 0.2, 1] as const },
  quick: { duration: 0.18 },
} as const;
