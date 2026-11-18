import { motion } from "framer-motion";
import { useState } from "react";
import { fmt } from "../../shared/data/summaries";
import type { Campaign, EvaluationData, Stat } from "../../shared/data/types";
import { Panel } from "../../shared/ui/Panel";
import { EmptyState } from "../../shared/ui/States";
import s from "./evaluation.module.css";

const ORDER = ["manual_ops", "manual_iso", "auto_naive", "platform"];

function cell(stat: Stat | undefined, digits: number, scale = 1, unit = "") {
  if (!stat || stat.mean === null) return "n/a";
  const sd = stat.n > 1 && stat.sd ? ` ± ${(stat.sd * scale).toFixed(digits)}` : "";
  return `${(stat.mean * scale).toFixed(digits)}${sd}${unit}`;
}

function Bars({ c }: { c: Campaign }) {
  const names = Object.keys(c.designs).sort(
    (a, b) =>
      (c.designs[b].summary.good_shots_per_day.mean ?? 0) -
      (c.designs[a].summary.good_shots_per_day.mean ?? 0),
  );
  const max = Math.max(...names.map((n) => c.designs[n].summary.good_shots_per_day.mean ?? 0), 1);
  return (
    <ul className={s.bars}>
      {names.map((n, i) => {
        const v = c.designs[n].summary.good_shots_per_day.mean ?? 0;
        return (
          <li key={n} className={s.bar}>
            <span className={s.barName}>{n.replaceAll("_", " ")}</span>
            <span className={s.barTrack}>
              <motion.span
                className={
                  n === "platform" ? s.barFillPlatform : n === "manual_ops" ? s.barFillStatus : s.barFill
                }
                initial={{ width: 0 }}
                animate={{ width: `${(v / max) * 100}%` }}
                transition={{ delay: 0.03 * i, duration: 0.4 }}
              />
            </span>
            <span className={s.barValue}>{v.toFixed(0)}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function EvaluationView({ data }: { data: EvaluationData }) {
  const available = (["dev", "heldout"] as const).filter((k) => data[k]);
  const [which, setWhich] = useState<"dev" | "heldout">(available[0] ?? "dev");
  const c = data[which];
  if (!c) {
    return (
      <EmptyState
        title="No evaluation yet"
        text="Run python3 -m evals.run, then python3 -m evals.console_data."
      />
    );
  }
  return (
    <div className={s.stack}>
      <fieldset className={s.switch} aria-label="Campaign">
        {available.map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={which === k}
            className={which === k ? s.on : s.off}
            onClick={() => setWhich(k)}
          >
            {k === "dev"
              ? `Dev: ${c && which === "dev" ? c.seeds.length : data.dev?.seeds.length} beamlines`
              : "Held-out: run once"}
          </button>
        ))}
        <span className={s.meta}>
          {c.days} shifts per beamline, commit {c.commit}. Simulation truth: these numbers score the platform
          against the simulated beamline's hidden state.
        </span>
      </fieldset>
      <Panel
        title="Good shots per shift"
        id="bars"
        note="In spec (pointing, centring, energy) and fired through an undamaged optic."
      >
        <Bars c={c} />
      </Panel>
      <Panel title="Designs on the same luck" id="designs">
        <div className={s.scroll}>
          <table className={s.table}>
            <thead>
              <tr>
                <th scope="col">Design</th>
                <th scope="col">Good shots / shift</th>
                <th scope="col">In spec</th>
                <th scope="col">Pointing p95, µrad</th>
                <th scope="col">Energy reading p95</th>
                <th scope="col">Damaging shots</th>
                <th scope="col">Alignment, min / shift</th>
              </tr>
            </thead>
            <tbody>
              {[...ORDER, ...Object.keys(c.designs).filter((n) => !ORDER.includes(n))]
                .filter((n) => c.designs[n])
                .map((n) => {
                  const d = c.designs[n].summary;
                  return (
                    <tr key={n} className={n === "platform" ? s.highlight : undefined}>
                      <th scope="row" title={c.designs[n].description}>
                        {n.replaceAll("_", " ")}
                      </th>
                      <td>{cell(d.good_shots_per_day, 0)}</td>
                      <td>{cell(d.in_spec_share, 1, 100, " %")}</td>
                      <td>{cell(d.ff_error_p95_urad, 1)}</td>
                      <td>{cell(d.energy_report_error_p95, 2, 100, " %")}</td>
                      <td>{cell(d.damage_events, 0)}</td>
                      <td>{cell(d.align_minutes_per_day, 0)}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel
        title="Release gates"
        id="gates"
        note="Applied to the platform design; the worst beamline counts."
      >
        <ul className={s.gates}>
          {c.gates.map((g) => (
            <li key={g.gate} className={g.pass ? s.pass : s.fail}>
              <span>{g.pass ? "Pass" : "Fail"}</span>
              <span>{g.gate.replaceAll("_", " ")}</span>
              <span>
                {fmt(g.value, 3)} {g.rule.max !== undefined ? `≤ ${g.rule.max}` : `≥ ${g.rule.min}`}
              </span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
