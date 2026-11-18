"""The repository's invariants (AGENTS.md), each as a test."""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_the_truth_stays_in_the_world():
    """The platform reaches the beamline only through device protocols: lbp/ never imports world/ or evals/."""
    for path in (ROOT / "lbp").rglob("*.py"):
        assert not imports(path) & {"world", "evals"}, path


def test_the_world_does_not_read_the_platforms_settings():
    for path in (ROOT / "world").rglob("*.py"):
        assert "lbp" not in imports(path), path
        assert "platform.toml" not in path.read_text() and "designs.toml" not in path.read_text(), path


def test_settings_live_in_config():
    """Every setting in config/platform.toml is read by the code (no dead settings), and no tuning constant
    hides in the control or calibration code as a literal."""
    cfg = tomllib.loads((ROOT / "config" / "platform.toml").read_text())
    leaves = set()

    def walk(d: dict) -> None:
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v)
            else:
                leaves.add(k)

    walk(cfg)
    code = "".join(p.read_text() for d in ("lbp", "evals", "scripts") for p in (ROOT / d).rglob("*.py"))
    unused = {k for k in leaves if f'"{k}"' not in code}
    assert not unused, f"settings nobody reads: {sorted(unused)}"
    allowed = {0.0, 0.5, 1.0, 2.0, 4.0, 9.0, 10.0, 1e-9, 1e-6, 1e-3, 1.4826, 60.0}  # units, guards, MAD
    for sub in ("control", "calibration"):
        for path in (ROOT / "lbp" / sub).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, float):
                    assert node.value in allowed, f"{path.name}: literal {node.value} belongs in config"


def test_same_luck_for_every_design(wcfg):
    """The world's randomness depends on the seed and the time, never on what a design did."""
    from world.beamline import Beamline

    a, b = Beamline(wcfg, 11), Beamline(wcfg, 11)
    a.start_day(2)
    b.start_day(2)
    a.move(0, 500)  # one design moves a mirror, the other does not
    b.advance(a.t)
    pa, pb = a.fire("low"), b.fire("low")
    jitter_a = pa.ff_urad - (a.matrix @ a.theta + a._day_offsets[2] + a._grid(a._walk))[2:]
    jitter_b = pb.ff_urad - (b.matrix @ b.theta + b._day_offsets[2] + b._grid(b._walk))[2:]
    assert a.hotspot_start == b.hotspot_start
    assert set(a.nf_cam.hot) == set(b.nf_cam.hot)
    assert np.allclose(jitter_a, jitter_b, atol=1e-6) or np.allclose(a._grid(a._walk), b._grid(b._walk))


def test_reports_are_generated():
    """The README's results are generated from reports/ and match them."""
    from evals import readme

    if not (ROOT / "reports" / "dev.json").exists():
        return
    assert readme.render_block() in (ROOT / "README.md").read_text()


def test_held_out_ran_once_behind_a_lock():
    out = ROOT / "reports" / "heldout.json"
    if not out.exists():
        return
    lock = json.loads((ROOT / "reports" / "heldout.lock").read_text())
    report = json.loads(out.read_text())
    assert lock["commit"] == report["commit"] and len(lock["commit"]) == 40
