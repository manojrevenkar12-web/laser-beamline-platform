import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { clock, fmt } from "../../shared/data/summaries";
import type { Held, Shot } from "../../shared/data/types";
import { Panel } from "../../shared/ui/Panel";
import { EmptyState } from "../../shared/ui/States";
import s from "./interlock.module.css";

const DAMAGE = 3.0;

function Gauge({ value, limit }: { value: number | null; limit: number }) {
  const pct = (x: number) => `${Math.min(100, (x / DAMAGE) * 100)}%`;
  return (
    <div
      className={s.gauge}
      aria-label={`Predicted peak fluence ${fmt(value, 2)} of limit ${fmt(limit, 2)} J/cm²`}
    >
      <div className={s.above}>
        <span>predicted peak {fmt(value, 2, "J/cm²")}</span>
        <span style={{ left: pct(limit) }} className={s.scaleMark}>
          limit {fmt(limit, 2)}
        </span>
      </div>
      <div className={s.track}>
        {value !== null ? <div className={s.fill} style={{ width: pct(value) }} /> : null}
        <div className={s.limit} style={{ left: pct(limit) }} />
      </div>
      <div className={s.scale}>
        <span>0</span>
        <span>damage {DAMAGE.toFixed(1)} J/cm²</span>
      </div>
    </div>
  );
}

export function InterlockPanel({ held, lastShot, limit }: { held: Held[]; lastShot?: Shot; limit: number }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel
      title="Interlocks"
      id="interlocks"
      note="Every full shot waits for the interlocks. The fluence check predicts the peak on the amplifier optics from the pre-shot near-field profile and the target energy."
    >
      <div className={s.now}>
        <span className={s.badgePermit}>Last shot permitted</span>
        <span className={s.meta}>
          {lastShot ? `${lastShot.shot_id} at ${clock(lastShot.t_s)}` : "no shot yet"}
        </span>
      </div>
      <Gauge value={lastShot?.predicted_fluence_j_cm2 ?? null} limit={limit} />
      <h3 className={s.subhead}>Held this shift ({held.length})</h3>
      {held.length === 0 ? (
        <EmptyState title="Nothing held" text="Every requested shot this shift passed the interlocks." />
      ) : (
        <ul className={s.list}>
          {held.map((h) => (
            <li key={h.decision_id}>
              <button
                type="button"
                className={s.item}
                aria-expanded={open === h.decision_id}
                onClick={() => setOpen(open === h.decision_id ? null : h.decision_id)}
              >
                <span className={s.badgeHold}>Held</span>
                <span className={s.time}>{clock(h.t_s)}</span>
                <span className={s.reason}>{h.reasons[0]}</span>
              </button>
              <AnimatePresence initial={false}>
                {open === h.decision_id ? (
                  <motion.div
                    className={s.detail}
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <p>All reasons: {h.reasons.join("; ")}.</p>
                    <p>
                      Predicted {fmt(h.predicted, 2, "J/cm²")}, limit {fmt(h.limit, 2, "J/cm²")}.{" "}
                      {h.action === "inspect" ? "The platform asked for an optics inspection." : ""}
                    </p>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
