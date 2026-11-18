import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { BeamlineSchematic } from "../features/beamline/BeamlineSchematic";
import { CalibrationView } from "../features/calibration/CalibrationView";
import { CameraView } from "../features/cameras/CameraView";
import { EvaluationView } from "../features/evaluation/EvaluationView";
import { InterlockPanel } from "../features/interlock/InterlockPanel";
import { ShotStrip } from "../features/shots/ShotStrip";
import { fmt, summarise } from "../shared/data/summaries";
import type { EvaluationData, ShiftData } from "../shared/data/types";
import { useJson } from "../shared/data/useJson";
import { motion as m } from "../shared/theme/tokens";
import { Panel } from "../shared/ui/Panel";
import { EmptyState, ErrorState, Skeleton, Stat } from "../shared/ui/States";
import s from "./app.module.css";

type Tab = "shift" | "calibration" | "evaluation";
const TABS: { id: Tab; label: string }[] = [
  { id: "shift", label: "Shift" },
  { id: "calibration", label: "Calibration" },
  { id: "evaluation", label: "Evaluation" },
];

function ShiftView({ data }: { data: ShiftData }) {
  const sum = summarise(data.shots, data.tolerance);
  const last = data.shots.filter((x) => x.purpose === "experiment").at(-1);
  const r = data.reference;
  if (sum.fired === 0) {
    return (
      <EmptyState title="No shots this shift" text="Start a shift; shots appear here as they are stored." />
    );
  }
  return (
    <div className={s.shift}>
      <div className={s.stats}>
        <Stat value={String(sum.fired)} label="experiment shots fired" />
        <Stat value={`${sum.withinTolerance}`} label="inside pointing and centring tolerance (measured)" />
        <Stat value={fmt(sum.ffP95, 1, "µrad")} label="pointing error, 95th percentile" />
        <Stat value={fmt(sum.meanEnergy, 2, "J")} label="mean reported energy" />
        <Stat value={String(data.log.blocked)} label="shots held" />
        <Stat
          value={fmt(data.log.align_minutes, 0, "min")}
          label={`alignment in ${data.log.alignments} runs`}
        />
      </div>
      <div className={s.columns}>
        <InterlockPanel held={data.held} lastShot={last} limit={2.25} />
        <Panel
          title={`Diagnostics of ${data.last_shot}`}
          id="cameras"
          note="Blue: reference and tolerance. Red: measured centroid and D4σ ellipse (ISO 11146)."
        >
          <div className={s.cameras}>
            <CameraView
              title="Near field"
              frame={data.frames.nf}
              refPx={r.nf_px}
              tolPx={data.tolerance.nf_mm / r.nf_mm_per_px}
              unitPerPx={r.nf_mm_per_px}
              unit="mm"
            />
            <CameraView
              title="Far field"
              frame={data.frames.ff}
              refPx={r.ff_px}
              tolPx={data.tolerance.ff_urad / r.ff_urad_per_px}
              unitPerPx={r.ff_urad_per_px}
              unit="µrad"
            />
          </div>
        </Panel>
      </div>
      <Panel title="Pointing through the shift" id="strip">
        <ShotStrip
          shots={data.shots}
          held={data.held}
          alignments={data.alignments}
          tolerance={data.tolerance.ff_urad}
        />
      </Panel>
      {data.alerts.length ? (
        <Panel title="Alerts" id="alerts">
          <ul className={s.alerts}>
            {data.alerts.map((a) => (
              <li key={`${a.t_s}-${a.kind}`} className={a.severity === "critical" ? s.critical : undefined}>
                {a.message}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

export function App() {
  const [tab, setTab] = useState<Tab>("shift");
  const [shift, retryShift] = useJson<ShiftData>("data/shift.json");
  const [evaluation, retryEval] = useJson<EvaluationData>("data/evaluation.json");
  const held = shift.state === "ready" && shift.data.held.length > 0;

  return (
    <div className={s.page}>
      <header className={s.header}>
        <div>
          <h1 className={s.title}>Beamline console</h1>
          <p className={s.sub}>
            {shift.state === "ready"
              ? `${shift.data.beamline}, shift ${shift.data.day}. Beam analysis: ${shift.data.engine}.`
              : "Loading the shift"}
          </p>
        </div>
        <nav className={s.tabs} aria-label="Views">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? s.tabOn : s.tab}
              aria-current={tab === t.id ? "page" : undefined}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {shift.state === "ready" ? (
        <BeamlineSchematic devices={shift.data.devices} held={false} />
      ) : (
        <Skeleton height={170} />
      )}
      {held ? <p className={s.heldNote}>The interlocks held shots this shift; see Interlocks.</p> : null}

      <AnimatePresence mode="wait">
        <motion.main
          key={tab}
          className={s.main}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={m.reveal}
        >
          {tab === "evaluation" ? (
            evaluation.state === "loading" ? (
              <Skeleton height={420} />
            ) : evaluation.state === "error" ? (
              <ErrorState what="the evaluation" message={evaluation.message} onRetry={retryEval} />
            ) : (
              <EvaluationView data={evaluation.data} />
            )
          ) : shift.state === "loading" ? (
            <div className={s.loading}>
              <Skeleton height={64} />
              <Skeleton height={360} />
              <Skeleton height={240} />
            </div>
          ) : shift.state === "error" ? (
            <ErrorState what="the shift" message={shift.message} onRetry={retryShift} />
          ) : tab === "shift" ? (
            <ShiftView data={shift.data} />
          ) : (
            <CalibrationView data={shift.data} />
          )}
        </motion.main>
      </AnimatePresence>
    </div>
  );
}
