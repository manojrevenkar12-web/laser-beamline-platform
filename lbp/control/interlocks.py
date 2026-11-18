"""Shot interlocks: code decides whether a full-energy shot may fire, and says why not.

`evaluate` is a pure function of what the platform knows at that moment. Every decision is recorded with its
inputs, so an operator can see which rule held the shot and with which numbers.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ShotInputs:
    energy_target_j: float
    pump: float
    device_faults: tuple[str, ...] = ()
    alignment_fault: str = ""
    diode_temp_c: float = float("nan")
    profile_peak_fraction: float | None = None  # from the latest near-field frame
    profile_saturated: bool = False
    profile_age_s: float = 0.0
    energy_cal_valid: bool = True
    beam_lost: bool = False  # the pre-shot pulse did not land on both diagnostic cameras
    alignment_error: float | None = None  # pre-shot error as a share of tolerance (largest axis)


@dataclass
class Decision:
    permit: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    predicted_fluence_j_cm2: float | None = None
    limit_j_cm2: float | None = None
    action: str = ""  # what the platform does next when the shot is held: "inspect", "service", ""

    def as_dict(self) -> dict:
        return asdict(self)


def predicted_fluence(energy_j: float, peak_fraction: float, mm_per_px: float) -> float:
    px_area_cm2 = (mm_per_px / 10.0) ** 2
    return energy_j * peak_fraction / px_area_cm2


def evaluate(x: ShotInputs, cfg: dict, fluence_interlock: bool) -> Decision:
    d = Decision(permit=True)
    e = cfg["energy"]
    if x.pump > float(e["pump_max"]) or x.pump < 0:
        d.reasons.append(f"pump {x.pump:.3f} outside 0..{e['pump_max']}")
    for name in x.device_faults:
        d.reasons.append(f"device {name} faulted")
        d.action = "service"
    if x.alignment_fault:
        d.reasons.append(x.alignment_fault)
        d.action = "service"
    lo, hi = e["diode_band_c"]
    if not math.isnan(x.diode_temp_c) and not lo <= x.diode_temp_c <= hi:
        d.reasons.append(f"diode temperature {x.diode_temp_c:.2f} C outside {lo}..{hi} C")
    if x.beam_lost:
        d.reasons.append("beam not on the diagnostic cameras")
    if x.alignment_error is not None and x.alignment_error > 1.0:
        d.reasons.append(f"pre-shot error at {x.alignment_error:.2f} of tolerance after alignment")
    if not x.energy_cal_valid:
        d.warnings.append("energy meter calibration not traceable")
    if fluence_interlock:
        f = cfg["fluence"]
        limit = float(f["damage_j_cm2"]) * float(f["safety_factor"])
        d.limit_j_cm2 = limit
        if x.profile_peak_fraction is None or not math.isfinite(x.profile_peak_fraction):
            d.reasons.append("no near-field profile to predict the fluence")
        elif x.profile_saturated:
            d.reasons.append("near-field profile saturated; fluence unknown")
        else:
            pf = predicted_fluence(x.energy_target_j, x.profile_peak_fraction, float(f["nf_mm_per_px_at_optic"]))
            d.predicted_fluence_j_cm2 = pf
            if pf > limit:
                d.reasons.append(f"predicted peak fluence {pf:.2f} J/cm2 above limit {limit:.2f} J/cm2")
                d.action = d.action or "inspect"
    d.permit = not d.reasons
    return d
