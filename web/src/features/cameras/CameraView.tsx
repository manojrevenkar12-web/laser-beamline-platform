import { motion } from "framer-motion";
import { fmt } from "../../shared/data/summaries";
import type { Frame } from "../../shared/data/types";
import { color } from "../../shared/theme/tokens";
import s from "./cameras.module.css";

interface Props {
  title: string;
  frame?: Frame;
  refPx: number[];
  tolPx: number;
  unitPerPx: number;
  unit: string;
}

/** A camera frame with the reference crosshair, the tolerance circle and the measured D4σ ellipse. */
export function CameraView({ title, frame, refPx, tolPx, unitPerPx, unit }: Props) {
  if (!frame) {
    return (
      <div className={s.empty}>
        <p className={s.title}>{title}</p>
        <p>No frame stored for this shot.</p>
      </div>
    );
  }
  const n = frame.size;
  const dx = (frame.cx - refPx[0]) * unitPerPx;
  const dy = (frame.cy - refPx[1]) * unitPerPx;
  return (
    <figure className={s.camera}>
      <div className={s.frame}>
        <img src={frame.src} alt={`${title} camera frame`} className={s.image} />
        <svg viewBox={`0 0 ${n} ${n}`} className={s.overlay} aria-hidden="true">
          <line x1={refPx[0]} x2={refPx[0]} y1="0" y2={n} stroke={color.calib} strokeWidth="0.4" />
          <line y1={refPx[1]} y2={refPx[1]} x1="0" x2={n} stroke={color.calib} strokeWidth="0.4" />
          <circle
            cx={refPx[0]}
            cy={refPx[1]}
            r={tolPx}
            fill="none"
            stroke={color.calib}
            strokeWidth="0.6"
            strokeDasharray="2 1.5"
          />
          <motion.ellipse
            cx={frame.cx}
            cy={frame.cy}
            rx={frame.d4x / 2}
            ry={frame.d4y / 2}
            fill="none"
            stroke={color.beam}
            strokeWidth="0.8"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6, duration: 0.4 }}
          />
          <circle cx={frame.cx} cy={frame.cy} r="0.9" fill={color.beam} />
        </svg>
      </div>
      <figcaption className={s.caption}>
        <span className={s.title}>{title}</span>
        <span>
          offset {fmt(dx, 2)}, {fmt(dy, 2)} {unit} ; D4σ {fmt(frame.d4x * unitPerPx, 1)} ×{" "}
          {fmt(frame.d4y * unitPerPx, 1)} {unit}
        </span>
        <span>{frame.saturated > 0 ? "saturated pixels in the beam" : "no saturation"}</span>
      </figcaption>
    </figure>
  );
}
