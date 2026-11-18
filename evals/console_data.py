"""Static data for the operator console (web/public/data/), from reports/ and a showcase run.

The console shows what the platform knows: measured positions, its interlock decisions, its calibrations.
Simulation truth appears only where it is labelled as such (the evaluation views).

    python3 -m evals.console_data
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from evals import showcase
from lbp.api.app import png
from lbp.diagnostics import native

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "data"


def _num(x: object) -> object:
    if isinstance(x, float):
        return None if not math.isfinite(x) else round(x, 5)
    return x


def _clean(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return _num(obj.item())
    return _num(obj)


def shift() -> dict:
    run = showcase.run("platform", frames=True)
    ops, day = run.ops, showcase.SHIFT
    shots = [s.row() for s in ops.shots if s.day == day]
    decisions = [
        {
            "decision_id": did,
            "t_s": t,
            "permit": d.permit,
            "reasons": d.reasons,
            "warnings": d.warnings,
            "predicted": d.predicted_fluence_j_cm2,
            "limit": d.limit_j_cm2,
            "action": d.action,
        }
        for (did, dd, t, _, d) in ops.decisions
        if dd == day and not d.permit
    ]
    aligns = [a.summary() for a in ops.alignments if a.day == day]
    alerts = [{"t_s": a.t_s, "severity": a.severity, "kind": a.kind, "message": a.message} for a in ops.alerts if a.day == day]
    last = [s for s in ops.shots if s.day == day][-1]
    frames = {}
    for cam in ("nf", "ff"):
        img = ops.store.frame(day, last.shot_id, cam)
        if img is None:
            continue
        cal = ops.cam_cal[cam]
        m = native.analyze(img, cal.dark if cal else None, cal.mask if cal else None, ops.opt)
        (OUT / f"{cam}.png").write_bytes(png(img))
        frames[cam] = {
            "src": f"data/{cam}.png",
            "size": int(img.shape[0]),
            "cx": m.cx,
            "cy": m.cy,
            "d4x": m.d4x,
            "d4y": m.d4y,
            "peak_fraction": m.peak_fraction,
            "saturated": m.saturated,
        }
    log = next(d for d in ops.days if d.day == day)
    return {
        "beamline": f"dev beamline {showcase.SEED}",
        "day": day,
        "engine": ops.engine,
        "tolerance": ops.cfg["tolerance"],
        "reference": ops.cfg["reference"],
        "shots": shots,
        "held": decisions,
        "alignments": aligns,
        "alerts": alerts,
        "matrix": ops.aligner.cal.summary(),
        "energy_cals": [c.summary() for c in ops.energy_cals],
        "devices": [d.health.as_dict() for d in ops.devices.values()],
        "frames": frames,
        "last_shot": last.shot_id,
        "log": {
            "fired": log.fired,
            "blocked": log.blocked,
            "alignments": log.alignments,
            "align_minutes": log.align_seconds / 60,
            "inspections": log.inspections,
        },
    }


def evaluation() -> dict:
    out = {}
    for name in ("dev", "heldout"):
        p = ROOT / "reports" / f"{name}.json"
        if not p.exists():
            continue
        rep = json.loads(p.read_text())
        out[name] = {
            "days": rep["days"],
            "seeds": rep["seeds"],
            "commit": rep["commit"][:7],
            "gates": rep["gates"],
            "designs": {n: {"description": d["description"], "summary": d["summary"]} for n, d in rep["designs"].items()},
        }
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "shift.json").write_text(json.dumps(_clean(shift()), indent=1) + "\n")
    (OUT / "evaluation.json").write_text(json.dumps(_clean(evaluation()), indent=1) + "\n")
    print("wrote web/public/data/")


if __name__ == "__main__":
    main()
