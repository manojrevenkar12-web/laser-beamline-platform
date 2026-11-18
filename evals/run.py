"""Run every design on the dev campaigns (or once on the held-out campaign) and check the gates.

    python3 -m evals.run                 # dev: all designs x dev seeds -> reports/dev.json
    python3 -m evals.run --days 3        # a quick look (not written to reports/)
    python3 -m evals.run --heldout       # once, behind reports/heldout.lock -> reports/heldout.json

Same luck: every design runs on the same seeds, and the world draws its randomness from streams keyed by time,
so the drift, the hot spots and the shot-to-shot jitter are the same whatever a design does.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import tomllib
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from evals.operate import operate, world_config
from evals.truth import score
from lbp import config

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
METRICS = (
    "shots_per_day",
    "good_shots_per_day",
    "in_spec_share",
    "ff_error_p50_urad",
    "ff_error_p95_urad",
    "nf_error_p95_mm",
    "energy_delivered_error_p95",
    "energy_report_error_p95",
    "damage_events",
    "max_fluence_j_cm2",
    "fluence_blocks",
    "false_fluence_blocks",
    "false_block_share",
    "blocked",
    "inspections",
    "align_minutes_per_day",
    "alignments_per_day",
    "calibration_minutes_per_day",
    "matrix_refreshes",
)


def _one(args: tuple[str, int, str, int | None]) -> dict:
    design, seed, world, days = args
    t0 = time.time()
    run = operate(design, seed, world=world, days=days)
    s = score(run)
    reasons = Counter("; ".join(d.reasons) for (_, _, _, _, d) in run.ops.decisions if not d.permit)
    s["block_reasons"] = [{"reason": k, "count": v} for k, v in reasons.most_common(4)]
    s["alerts_list"] = [
        {"day": a.day, "kind": a.kind, "severity": a.severity, "message": a.message} for a in run.ops.alerts if a.kind != "hot-pixels"
    ]
    s["engine"] = run.ops.engine
    s["seconds"] = round(time.time() - t0, 1)
    if design == "platform":
        s["daily"] = [
            {
                "day": d.day,
                "fired": d.fired,
                "blocked": d.blocked,
                "alignments": d.alignments,
                "align_minutes": round(d.align_seconds / 60, 2),
                "calibration_minutes": round(d.calibration_seconds / 60, 2),
                "inspections": d.inspections,
            }
            for d in run.ops.days
        ]
        s["energy_cals"] = [c.summary() for c in run.ops.energy_cals]
        s["matrix"] = run.ops.aligner.cal.summary()
        s["true_matrix_per_step"] = np.round(run.world.matrix * run.world.step[None, :], 6).tolist()
    return s


def aggregate(rows: list[dict]) -> dict:
    out: dict = {}
    for m in METRICS:
        vals = [r[m] for r in rows if isinstance(r[m], (int, float)) and math.isfinite(r[m])]
        if not vals:
            out[m] = {"mean": None, "sd": None, "min": None, "max": None, "n": 0}
            continue
        out[m] = {
            "mean": float(np.mean(vals)),
            "sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "n": len(vals),
        }
    return out


def gates(summary: dict) -> list[dict]:
    with open(ROOT / "config" / "gates.toml", "rb") as fh:
        g = tomllib.load(fh)["gates"]
    plat = summary["platform"]
    manual = summary.get("manual_ops")
    results = []
    for name, rule in g.items():
        if name == "good_shots_per_day_vs_manual":
            if not manual:
                continue
            m = manual["good_shots_per_day"]["mean"] or 0.0
            value = plat["good_shots_per_day"]["mean"] / m if m > 0 else math.inf
        else:
            stat = plat[name]
            # the gate holds on the worst seed, not the average
            value = stat["max"] if "max" in rule else stat["min"]
        ok = (value <= rule["max"]) if "max" in rule else (value >= rule["min"])
        results.append({"gate": name, "value": value, "rule": rule, "pass": bool(ok)})
    return results


def commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout", action="store_true")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--designs", default="")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args(argv)

    world = "heldout" if args.heldout else "world"
    wcfg = world_config(world)
    seeds = [int(s) for s in wcfg["campaign"]["dev_seeds"]]
    names = [n for n in config.designs() if not args.designs or n in args.designs.split(",")]
    if args.heldout:
        lock = REPORTS / "heldout.lock"
        if (REPORTS / "heldout.json").exists():
            print("reports/heldout.json exists: the held-out campaign runs once. See docs/heldout.md.")
            return 2
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "lbp", "config", "evals", "world"], cwd=ROOT, capture_output=True, text=True
        ).stdout
        if dirty.strip():
            print("commit the platform before the held-out run; uncommitted changes:\n" + dirty)
            return 2
        lock.write_text(json.dumps({"commit": commit(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2) + "\n")

    jobs = [(n, s, world, args.days) for n in names for s in seeds]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_one, jobs))
    by_design: dict[str, list[dict]] = {}
    for r in rows:
        by_design.setdefault(r["design"], []).append(r)
    summary = {n: aggregate(by_design[n]) for n in names}
    report = {
        "world": world,
        "seeds": seeds,
        "days": args.days or int(wcfg["campaign"]["days"]),
        "commit": commit(),
        "designs": {n: {"description": config.design(n).description, "summary": summary[n], "runs": by_design[n]} for n in names},
        "gates": gates(summary) if "platform" in summary else [],
        "seconds": round(time.time() - t0, 1),
    }
    for n in names:
        s = summary[n]
        print(
            f"{n:20s} good/day {s['good_shots_per_day']['mean']:6.1f}  in spec {s['in_spec_share']['mean']:.3f}  "
            f"ff p95 {s['ff_error_p95_urad']['mean'] if s['ff_error_p95_urad']['mean'] is not None else float('nan'):7.2f}  "
            f"damage {s['damage_events']['mean']:6.1f}  false blocks {s['false_block_share']['mean']:.3f}"
        )
    for g in report["gates"]:
        print(f"gate {g['gate']:32s} {g['value']:.4f} {'pass' if g['pass'] else 'FAIL'}")
    if args.days is None or args.heldout:
        REPORTS.mkdir(exist_ok=True)
        out = REPORTS / ("heldout.json" if args.heldout else "dev.json")
        out.write_text(json.dumps(report, indent=1, default=float) + "\n")
        print(f"wrote {out.relative_to(ROOT)} in {report['seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
