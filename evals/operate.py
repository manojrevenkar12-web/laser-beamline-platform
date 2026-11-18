"""Run one design on one simulated campaign: the beamline, its emulators, the platform's drivers and operations.

This is the only place that holds both sides: it builds the world, connects the platform to it through
loopback (or TCP) transports, and hands the world back to evals/truth.py for scoring.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from lbp import config
from lbp.control.interlocks import Decision, ShotInputs
from lbp.control.operations import Operations
from lbp.data.store import Store
from lbp.devices.drivers import Camera, EnergyMeter, Laser, Picomotor, ReferenceMeter
from lbp.devices.transport import LoopbackTransport, TcpTransport
from world.beamline import Beamline
from world.emulators import SimClock, build

ROOT = Path(__file__).resolve().parent.parent
DRIVERS = {"pmc": Picomotor, "lcu": Laser, "em": EnergyMeter, "ref": ReferenceMeter, "nfc": Camera, "ffc": Camera}


def world_config(name: str = "world") -> dict:
    with open(ROOT / "config" / f"{name}.toml", "rb") as fh:
        return tomllib.load(fh)


@dataclass
class Run:
    design: str
    seed: int
    world: Beamline
    ops: Operations
    fluence_checks: list[tuple[int, float, ShotInputs, Decision, float]]


def connect(line: Beamline, cfg: dict, ports: dict[str, int] | None = None) -> dict:
    emulators = build(line)
    retries = int(cfg["devices"]["retries"])
    if cfg["devices"]["transport"] == "tcp" and ports is None:
        raise ValueError("the tcp transport needs the device ports (world.servers.serve)")
    devices = {}
    for name, cls in DRIVERS.items():
        if ports is None:
            transport = LoopbackTransport(emulators[name])
        else:
            transport = TcpTransport(cfg["devices"]["tcp"]["host"], ports[name], float(cfg["devices"]["timeout_s"]))
        devices[name] = cls(name, transport, retries=retries)
    return devices


def operate(
    design_name: str,
    seed: int,
    world: str = "world",
    days: int | None = None,
    store_root: str | None = None,
    frames: bool = False,
    bus: object | None = None,
) -> Run:
    wcfg = world_config(world)
    cfg = config.load()
    design = config.design(design_name)
    line = Beamline(wcfg, seed)
    clock = SimClock(line)
    devices = connect(line, cfg)
    checks: list[tuple[int, float, ShotInputs, Decision, float]] = []

    def on_decision(inputs: ShotInputs, decision: Decision) -> None:
        # the referee notes what a full shot at the target energy would truly have done at this moment
        if any("fluence" in r for r in decision.reasons):
            checks.append((line.day, line.t, inputs, decision, truth_peak_at_target(line, inputs.energy_target_j)))

    store = Store.from_config(cfg, root=store_root, frames=frames) if store_root else None
    ops = Operations(cfg, design, devices, clock, store=store, bus=bus, on_decision=on_decision)
    n = days if days is not None else line.days
    for day in range(n):
        line.start_day(day)
        ops.run_day(day)
    return Run(design_name, seed, line, ops, checks)


def truth_peak_at_target(line: Beamline, energy_j: float) -> float:
    """The true peak fluence of a full shot at `energy_j` fired now, without jitter (referee only)."""
    pos = line.beam_position()
    prof, clipped = line.profile(pos[:2])
    mm = float(line.cfg["nf_camera"]["mm_per_px"])
    return float(energy_j * (1 - clipped) * prof.max() / prof.sum() / (mm / 10.0) ** 2)
