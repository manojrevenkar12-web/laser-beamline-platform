"""The referee: score a run against the beamline's hidden truth.

Only this module and evals/operate.py read the world's state. The spec of a good shot comes from the
experiment's requirements in config/platform.toml (tolerance), the damage threshold from the world.
"""

from __future__ import annotations

import math

import numpy as np

from evals.operate import Run
from lbp import config


def _p(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else float("nan")


def score(run: Run) -> dict:
    cfg = config.load()
    tol = cfg["tolerance"]
    target = float(cfg["energy"]["target_j"])
    limit = float(cfg["fluence"]["damage_j_cm2"]) * float(cfg["fluence"]["safety_factor"])
    world = run.world
    pulses = {p.pulse_id: p for p in world.pulses}
    days = max(1, len(run.ops.days))
    exp = [s for s in run.ops.shots if s.purpose == "experiment"]
    ff, nf, de, rep, good = [], [], [], [], 0
    for s in exp:
        p = pulses[s.pulse_id]
        f = float(np.hypot(*p.ff_urad))
        n = float(np.hypot(*p.nf_mm))
        e = p.energy_j / target - 1.0
        ff.append(f)
        nf.append(n)
        de.append(abs(e))
        if s.energy_reported_j is not None and p.energy_j > 0:
            rep.append(abs(s.energy_reported_j / p.energy_j - 1.0))
        if f <= tol["ff_urad"] and n <= tol["nf_mm"] and abs(e) <= tol["energy_rel"] and not p.damaged:
            good += 1
    full = [p for p in world.pulses if p.kind == "full"]
    damage = sum(1 for p in full if p.damaged)
    blocks = run.fluence_checks
    false_blocks = sum(1 for (_, _, _, _, truth) in blocks if truth <= limit)
    requested = len(exp) + sum(d.blocked for d in run.ops.days)
    align_s = sum(d.align_seconds for d in run.ops.days)
    return {
        "design": run.design,
        "seed": run.seed,
        "days": days,
        "shots_per_day": len(exp) / days,
        "good_shots_per_day": good / days,
        "in_spec_share": good / len(exp) if exp else 0.0,
        "ff_error_p50_urad": _p(ff, 50),
        "ff_error_p95_urad": _p(ff, 95),
        "nf_error_p95_mm": _p(nf, 95),
        "energy_delivered_error_p95": _p(de, 95),
        "energy_report_error_p95": _p(rep, 95),
        "damage_events": damage,
        "max_fluence_j_cm2": max((p.peak_fluence_j_cm2 for p in full), default=0.0),
        "fluence_blocks": len(blocks),
        "false_fluence_blocks": false_blocks,
        "false_block_share": false_blocks / requested if requested else 0.0,
        "blocked": sum(d.blocked for d in run.ops.days),
        "inspections": sum(d.inspections for d in run.ops.days),
        "align_minutes_per_day": align_s / 60.0 / days,
        "alignments_per_day": sum(d.alignments for d in run.ops.days) / days,
        "calibration_minutes_per_day": sum(d.calibration_seconds for d in run.ops.days) / 60.0 / days,
        "matrix_refreshes": sum(1 for a in run.ops.alignments if a.refreshed),
        "alerts": len(run.ops.alerts),
        "hot_spot_days": sorted({e.day for e in world.events if e.kind == "hotspot"}),
        "first_damage_day": min((p.day for p in full if p.damaged), default=None),
        "world_events": _events(world.events),
    }


def _events(events: list) -> list[dict]:
    """World events, with damage reduced to the first damaging shot of each day and a count."""
    out, damage_days = [], {}
    for e in events:
        if e.kind == "damage":
            damage_days.setdefault(e.day, []).append(e)
            continue
        out.append({"day": e.day, "t_s": round(e.t_s), "kind": e.kind, "detail": e.detail})
    for day, evs in damage_days.items():
        out.append({"day": day, "t_s": round(evs[0].t_s), "kind": "damage", "detail": f"{len(evs)} damaging shots, first {evs[0].detail}"})
    return sorted(out, key=lambda x: (x["day"], x["t_s"]))


def finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
