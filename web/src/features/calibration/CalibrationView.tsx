import { clock, fmt } from "../../shared/data/summaries";
import type { ShiftData } from "../../shared/data/types";
import { Panel } from "../../shared/ui/Panel";
import { EmptyState } from "../../shared/ui/States";
import s from "./calibration.module.css";

const AXES = ["M1x", "M1y", "M2x", "M2y"];
const ROWS = ["near field x, mm", "near field y, mm", "far field x, µrad", "far field y, µrad"];

export function CalibrationView({ data }: { data: ShiftData }) {
  const m = data.matrix;
  return (
    <div className={s.grid}>
      <Panel
        title="Interaction matrix"
        id="matrix"
        note={`Measured on the beamline (${m.cal_id}): beam motion per forward actuator step. Backlash is added after every reversal and reverse steps are scaled by their ratio. Condition number ${fmt(m.condition, 0)}.`}
      >
        <table className={s.table}>
          <thead>
            <tr>
              <th scope="col">Per step</th>
              {AXES.map((a) => (
                <th key={a} scope="col">
                  {a}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {m.matrix.map((row, i) => (
              <tr key={ROWS[i]}>
                <th scope="row">{ROWS[i]}</th>
                {row.map((v, j) => (
                  <td key={AXES[j]}>{i < 2 ? (v * 1000).toFixed(2) : v.toFixed(3)}</td>
                ))}
              </tr>
            ))}
            <tr className={s.mech}>
              <th scope="row">backlash, steps</th>
              {m.backlash.map((v, j) => (
                <td key={AXES[j]}>{v.toFixed(0)}</td>
              ))}
            </tr>
            <tr className={s.mech}>
              <th scope="row">reverse / forward step</th>
              {m.reverse_ratio.map((v, j) => (
                <td key={AXES[j]}>{v.toFixed(2)}</td>
              ))}
            </tr>
          </tbody>
        </table>
        <p className={s.footnote}>Near-field rows in µm per step.</p>
      </Panel>
      <Panel
        title="Energy meter cross-calibration"
        id="energy"
        note="Ten paired readings against a reference meter with a valid certificate, every third shift. A factor is applied only when its expanded uncertainty is within 1.5 %."
      >
        {data.energy_cals.length === 0 ? (
          <EmptyState
            title="No cross-calibration yet"
            text="The first one runs at the start of the first shift."
          />
        ) : (
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Calibration</th>
                <th scope="col">Shift</th>
                <th scope="col">Factor</th>
                <th scope="col">Change</th>
                <th scope="col">U (k = 2)</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {data.energy_cals.map((c) => (
                <tr key={c.cal_id}>
                  <td>{c.cal_id}</td>
                  <td>{c.day}</td>
                  <td>{c.factor.toFixed(4)}</td>
                  <td>{(100 * c.change).toFixed(2)} %</td>
                  <td>{(100 * c.u_k2).toFixed(2)} %</td>
                  <td>{c.applied ? "applied" : c.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <Panel
        title="Alignment runs this shift"
        id="aligns"
        note="Why each ran, how long it took and where it left the beam."
      >
        {data.alignments.length === 0 ? (
          <EmptyState
            title="No alignment this shift"
            text="The pre-shot pulses stayed inside 60 % of tolerance."
          />
        ) : (
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Start</th>
                <th scope="col">Reason</th>
                <th scope="col">Iterations</th>
                <th scope="col">Seconds</th>
                <th scope="col">Far field after, µrad</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {data.alignments.map((a) => (
                <tr key={`${a.started_s}-${a.reason}`}>
                  <td>{clock(a.started_s % 86400)}</td>
                  <td>{a.reason}</td>
                  <td>{a.iterations}</td>
                  <td>{a.seconds.toFixed(0)}</td>
                  <td>{Math.hypot(a.final_error[2], a.final_error[3]).toFixed(2)}</td>
                  <td>
                    {a.fault || (a.converged ? "converged" : "inside tolerance")}
                    {a.refreshed ? ", matrix refreshed" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
