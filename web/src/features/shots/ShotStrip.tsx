import { useMemo, useState } from "react";
import { clock, fmt, magnitude } from "../../shared/data/summaries";
import type { Alignment, Held, Shot } from "../../shared/data/types";
import { color } from "../../shared/theme/tokens";
import s from "./shots.module.css";

const W = 1000;
const H = 240;
const PAD = { l: 44, r: 12, t: 12, b: 44 };
const SHIFT_S = 8 * 3600;

interface Props {
  shots: Shot[];
  held: Held[];
  alignments: Alignment[];
  tolerance: number;
}

/** Measured pointing of every shot through the shift, with holds and alignments on the same clock. */
export function ShotStrip({ shots, held, alignments, tolerance }: Props) {
  const [hover, setHover] = useState<Shot | null>(null);
  const points = useMemo(
    () =>
      shots
        .filter((x) => x.purpose === "experiment")
        .map((x) => ({ shot: x, ff: magnitude(x.ff_x_urad, x.ff_y_urad) }))
        .filter((p): p is { shot: Shot; ff: number } => p.ff !== null),
    [shots],
  );
  const ymax = Math.max(tolerance * 2, ...points.map((p) => Math.min(p.ff, tolerance * 4)));
  const x = (t: number) => PAD.l + (t / SHIFT_S) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - Math.min(v, ymax) / ymax) * (H - PAD.t - PAD.b);
  const hours = Array.from({ length: 9 }, (_, i) => i);
  return (
    <div className={s.wrap}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={s.svg}
        role="img"
        aria-label="Measured far-field pointing error per shot through the shift"
      >
        {held.map((h) => (
          <rect
            key={h.decision_id}
            x={x(h.t_s) - 1.5}
            width="3"
            y={PAD.t}
            height={H - PAD.t - PAD.b}
            fill={color.hold}
          />
        ))}
        <rect
          x={PAD.l}
          y={y(tolerance)}
          width={W - PAD.l - PAD.r}
          height={y(0) - y(tolerance)}
          fill={color.permitSoft}
        />
        <line
          x1={PAD.l}
          x2={W - PAD.r}
          y1={y(tolerance)}
          y2={y(tolerance)}
          stroke={color.permit}
          strokeWidth="1"
        />
        <text x={W - PAD.r} y={y(tolerance) - 4} textAnchor="end" className={s.axis}>
          tolerance {tolerance} µrad
        </text>
        {hours.map((h) => (
          <text key={h} x={x(h * 3600)} y={H - PAD.b + 16} textAnchor="middle" className={s.axis}>
            {h}h
          </text>
        ))}
        {[0, ymax / 2, ymax].map((v) => (
          <text key={v} x={PAD.l - 6} y={y(v) + 4} textAnchor="end" className={s.axis}>
            {v.toFixed(0)}
          </text>
        ))}
        {alignments.map((a) => {
          const t0 = a.started_s % 86400; // alignment starts are stamped on the campaign clock
          return (
            <rect
              key={`${a.started_s}-${a.reason}`}
              x={x(t0)}
              width={Math.max(2, x(t0 + a.seconds) - x(t0))}
              y={H - PAD.b + 24}
              height="8"
              fill={color.calib}
            />
          );
        })}
        <text x={PAD.l} y={H - 4} className={s.axis}>
          Blue bars are alignment runs, yellow lines are shots held by the interlocks; µrad measured on the
          far-field camera
        </text>
        {points.map((p) => (
          <circle
            key={p.shot.shot_id}
            cx={x(p.shot.t_s)}
            cy={y(p.ff)}
            r={hover?.shot_id === p.shot.shot_id ? 5 : 3}
            fill={p.ff <= tolerance ? color.beam : color.ink}
            onMouseEnter={() => setHover(p.shot)}
            onMouseLeave={() => setHover(null)}
          >
            <title>{`${p.shot.shot_id} at ${clock(p.shot.t_s)}: ${p.ff.toFixed(2)} µrad`}</title>
          </circle>
        ))}
      </svg>
      <p className={s.readout} aria-live="polite">
        {hover
          ? `${hover.shot_id} at ${clock(hover.t_s)}: pointing ${fmt(magnitude(hover.ff_x_urad, hover.ff_y_urad), 2, "µrad")}, centring ${fmt(magnitude(hover.nf_x_mm, hover.nf_y_mm), 2, "mm")}, energy ${fmt(hover.energy_reported_j, 2, "J")}`
          : "Point at a shot to read it."}
      </p>
    </div>
  );
}
