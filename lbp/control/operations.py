"""Beamline operations: the shift, the shot cycle and every decision in it.

One `Operations` object runs a beamline through its devices. A shift starts with dark frames, energy
cross-calibration when due, the interaction matrix and an alignment. Each shot cycle fires a pre-shot
low-energy pulse, realigns when the beam has drifted past its share of tolerance, asks the interlocks, fires
the full shot, measures it and stores it with the calibrations behind every number.

The design (config/designs.toml) switches capabilities off to compare with the status quo; the code paths are
the same.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from lbp.bus.dds import AlertMsg, AlignmentMsg, HealthMsg, InterlockMsg, NullBus, ShotMsg
from lbp.calibration import energy as energy_cal
from lbp.calibration.alignment import Aligner, AlignResult, Measurement
from lbp.calibration.camera import CameraCal, measure_dark, next_exposure
from lbp.config import Design
from lbp.control.interlocks import Decision, ShotInputs, evaluate, predicted_fluence
from lbp.data.store import Store
from lbp.devices.drivers import Camera, Device, DeviceError, EnergyMeter, Laser, Picomotor, ReferenceMeter
from lbp.devices.transport import DeviceTimeout
from lbp.diagnostics import native
from lbp.diagnostics.beam import Metrics, Options


@dataclass
class Alert:
    alert_id: str
    day: int
    t_s: float
    severity: str
    kind: str
    message: str


@dataclass
class ShotRecord:
    shot_id: str
    pulse_id: int
    day: int
    t_s: float
    purpose: str
    pump: float
    energy_target_j: float
    energy_raw_j: float | None
    energy_reported_j: float | None
    error: list[float]
    nf_d4_mm: float
    peak_fraction: float
    fluence_est_j_cm2: float | None
    predicted_fluence_j_cm2: float | None
    saturated: bool
    pre_error: list[float] | None
    calibrations: dict
    decision_id: str

    def row(self) -> dict:
        return {
            "shot_id": self.shot_id,
            "pulse_id": self.pulse_id,
            "day": self.day,
            "t_s": round(self.t_s, 3),
            "purpose": self.purpose,
            "pump": round(self.pump, 5),
            "energy_target_j": self.energy_target_j,
            "energy_raw_j": self.energy_raw_j,
            "energy_reported_j": self.energy_reported_j,
            "nf_x_mm": self.error[0],
            "nf_y_mm": self.error[1],
            "ff_x_urad": self.error[2],
            "ff_y_urad": self.error[3],
            "nf_d4_mm": self.nf_d4_mm,
            "peak_fraction": self.peak_fraction,
            "fluence_est_j_cm2": self.fluence_est_j_cm2,
            "predicted_fluence_j_cm2": self.predicted_fluence_j_cm2,
            "saturated": int(self.saturated),
            "pre_error": self.pre_error,
            "calibrations": self.calibrations,
            "decision_id": self.decision_id,
        }


class AutoApprover:
    """Stands in for the second person on high-energy shots in simulation; a real console asks a person."""

    def approve(self, shot_id: str, energy_j: float) -> str:
        return "operator-sim"


def _finite(m: Metrics | None) -> bool:
    return m is not None and m.total > 0 and math.isfinite(m.cx) and math.isfinite(m.cy)


@dataclass
class DayLog:
    day: int
    align_seconds: float = 0.0
    alignments: int = 0
    inspections: int = 0
    blocked: int = 0
    fired: int = 0
    calibration_seconds: float = 0.0
    extra: dict = field(default_factory=dict)


class Operations:
    def __init__(
        self,
        cfg: dict,
        design: Design,
        devices: dict[str, Device],
        clock: object,
        store: Store | None = None,
        bus: object | None = None,
        approver: object | None = None,
        on_decision: Callable[[ShotInputs, Decision], None] | None = None,
    ):
        self.cfg, self.design, self.clock = cfg, design, clock
        self.pmc: Picomotor = devices["pmc"]  # type: ignore[assignment]
        self.lcu: Laser = devices["lcu"]  # type: ignore[assignment]
        self.em: EnergyMeter = devices["em"]  # type: ignore[assignment]
        self.ref: ReferenceMeter = devices["ref"]  # type: ignore[assignment]
        self.cams: dict[str, Camera] = {"nf": devices["nfc"], "ff": devices["ffc"]}  # type: ignore[dict-item]
        self.devices = devices
        for dev in devices.values():
            dev.health.fault_after = int(cfg["devices"]["fault_after_failures"])
        self.pmc.max_command = int(cfg["alignment"]["max_step_command"])
        self.store = store or Store(None, frames=False)
        self.bus = bus or NullBus()
        self.approver = approver or AutoApprover()
        self.on_decision = on_decision
        self.opt = Options.from_config(cfg["camera"], design)
        self.cam_cal: dict[str, CameraCal | None] = {"nf": None, "ff": None}
        start = float(cfg["camera"]["exposure_start"])
        self.exposure = {(c, k): start for c in ("nf", "ff") for k in ("low", "full")}
        self.aligner = Aligner(cfg, design, self.pmc, self.measure_low, clock)
        e = cfg["energy"]
        self.gain = float(e["gain_start_j_per_pump"])
        self.em_factor = 1.0
        self.em_history: list[tuple[float, float]] = []  # (fractional day, applied factor)
        self.em_cal_id = "vendor-certificate"
        self.em_cal_day: int | None = 0
        self.last_nf: Metrics | None = None
        self.last_shot_error: np.ndarray | None = None
        self.shots_since_align = 0
        self._shot_ids = itertools.count(1)
        self._decision_ids = itertools.count(1)
        self._alert_ids = itertools.count(1)
        self.shots: list[ShotRecord] = []
        self.decisions: list[tuple[str, int, float, ShotInputs, Decision]] = []
        self.alignments: list[AlignResult] = []
        self.alerts: list[Alert] = []
        self.energy_cals: list[energy_cal.EnergyCal] = []
        self.days: list[DayLog] = []
        self.log: DayLog | None = None
        self.engine = native.ENGINE

    # ------------------------------------------------------------------ helpers

    def now(self) -> float:
        return float(self.clock.seconds_into_day())  # type: ignore[attr-defined]

    def day(self) -> int:
        return int(self.clock.day())  # type: ignore[attr-defined]

    def alert(self, kind: str, severity: str, message: str) -> None:
        if any(a.kind == kind and a.day == self.day() and a.message == message for a in self.alerts):
            return
        a = Alert(f"alert-{next(self._alert_ids):05d}", self.day(), self.now(), severity, kind, message)
        self.alerts.append(a)
        self.store.put_alert(a.alert_id, a.day, a.t_s, severity, kind, message)
        self.bus.publish("lbp/alert", AlertMsg(a.alert_id, a.day, a.t_s, severity, kind, message))

    def _cal_ids(self) -> dict:
        return {
            "nf_camera": self.cam_cal["nf"].cal_id if self.cam_cal["nf"] else None,
            "ff_camera": self.cam_cal["ff"].cal_id if self.cam_cal["ff"] else None,
            "matrix": self.aligner.cal.cal_id,
            "energy": self.em_cal_id,
        }

    def _fractional_day(self) -> float:
        return self.day() + self.now() / float(self.clock.day_length())  # type: ignore[attr-defined]

    def energy_factor(self) -> float:
        """The meter factor now: the last cross-calibration, extrapolated along the drift seen between the
        last two (a pyroelectric head loses sensitivity steadily)."""
        if not self.cfg["energy"]["drift_correction"] or len(self.em_history) < 2:
            return self.em_factor
        (d0, f0), (d1, f1) = self.em_history[-2], self.em_history[-1]
        if d1 - d0 < 0.5:
            return self.em_factor
        slope = (f1 - f0) / (d1 - d0)
        return f1 + slope * (self._fractional_day() - d1)

    def _usable_profile(self, nf: Metrics | None) -> bool:
        """A near-field profile the fluence prediction may use. Designs with exposure control refuse a
        saturated one; designs without it do not know the difference."""
        if not _finite(nf) or nf is None or nf.edge:
            return False
        return nf.saturated <= 0 or not self.design.auto_exposure

    def _energy_traceable(self) -> bool:
        if self.em_cal_day is None:
            return False
        return self.day() - self.em_cal_day <= int(self.cfg["energy"]["max_cal_age_days"])

    # ------------------------------------------------------------------ measurement

    def frame_metrics(self, cam: str, pulse_id: int, kind: str) -> tuple[Metrics, np.ndarray]:
        exposure = self.exposure[(cam, kind)]
        frame = self.cams[cam].frame(pulse_id, exposure)
        cal = self.cam_cal[cam]
        dark = cal.dark if cal is not None else None
        mask = cal.mask if cal is not None else None
        m = native.analyze(frame.image, dark, mask, self.opt)
        if self.design.auto_exposure:
            level = (
                float(cal.dark.mean())
                if cal is not None
                else float(self.cfg["camera"]["full_scale"]) * float(self.cfg["camera"]["assumed_dark_fraction"])
            )
            self.exposure[(cam, kind)] = next_exposure(exposure, m.peak, level, m.saturated, self.cfg["camera"])
        return m, frame.image

    def error_of(self, nf: Metrics, ff: Metrics) -> np.ndarray:
        r = self.cfg["reference"]
        return np.array(
            [
                (nf.cx - r["nf_px"][0]) * r["nf_mm_per_px"],
                (nf.cy - r["nf_px"][1]) * r["nf_mm_per_px"],
                (ff.cx - r["ff_px"][0]) * r["ff_urad_per_px"],
                (ff.cy - r["ff_px"][1]) * r["ff_urad_per_px"],
            ]
        )

    def measure_low(self, k: int) -> Measurement:
        errs, lost, nf_last = [], False, None
        for _ in range(k):
            pid = self.lcu.fire_low()
            nf, _ = self.frame_metrics("nf", pid, "low")
            ff, _ = self.frame_metrics("ff", pid, "low")
            if not (_finite(nf) and _finite(ff)) or nf.edge or ff.edge:
                lost = True
            if _finite(nf) and _finite(ff):
                errs.append(self.error_of(nf, ff))
            nf_last = nf
            if self._usable_profile(nf):
                self.last_nf = nf  # every low pulse is a fresh near-field profile
        error = np.mean(errs, axis=0) if errs else np.zeros(4)
        return Measurement(error=error, lost=lost or not errs, nf=nf_last)

    def preshot(self) -> Measurement:
        attempts = int(self.cfg["camera"]["auto_exposure_attempts"]) if self.design.auto_exposure else 1
        m = self.measure_low(1)
        for _ in range(attempts - 1):
            if m.nf is None or m.nf.saturated <= 0:
                break
            m = self.measure_low(1)
        return m

    # ------------------------------------------------------------------ the start of a shift

    def calibrate_cameras(self) -> None:
        if not (self.design.analysis == "iso" and (self.design.background or self.design.hot_pixel_mask)):
            return
        for cam in ("nf", "ff"):
            cal = measure_dark(self.cams[cam], self.exposure[(cam, "low")], self.day(), self.cfg["camera"])
            self.cam_cal[cam] = cal
            self.store.put_calibration("camera", self.day(), self.now(), cal.summary())
            if cal.hot_pixels:
                self.alert("hot-pixels", "info", f"{cam} camera: {cal.hot_pixels} hot pixels masked")

    def cross_calibrate_energy(self) -> None:
        e = self.cfg["energy"]
        t0 = self.now()
        due = self.ref.due_day()
        if self.day() > due:
            self.alert("reference-overdue", "warning", f"reference meter certificate expired on day {due}; energy factor not recalibrated")
            return
        pre = self.preshot()
        inputs = self._inputs(pre.nf, purpose="calibration")
        decision = self._decide(inputs)
        if not decision.permit:
            self._handle_block(decision)
            return
        u_ref = self.ref.uncertainty_k2()
        self.lcu.reference(True)
        raws, refs = [], []
        try:
            for i in range(int(e["cross_cal_shots"])):
                if i:
                    self.clock.sleep(float(self.cfg["schedule"]["shot_cadence_s"]))  # type: ignore[attr-defined]
                rec = self._fire(inputs, decision, purpose="calibration")
                if rec is None:
                    break
                raws.append(rec.energy_raw_j or 0.0)
                refs.append(self.ref.read() or 0.0)
        finally:
            self.lcu.reference(False)
        cal = energy_cal.evaluate(self.day(), raws, refs, u_ref, self.em_factor, float(e["max_uncertainty_k2"]))
        self.energy_cals.append(cal)
        self.store.put_calibration("energy", self.day(), self.now(), cal.summary())
        if cal.applied:
            self.em_factor, self.em_cal_id, self.em_cal_day = cal.factor, cal.cal_id, self.day()
            self.em_history.append((self._fractional_day(), cal.factor))
        else:
            self.alert("energy-cal", "warning", f"energy cross-calibration not applied: {cal.reason}")
        if self.log:
            self.log.calibration_seconds += self.now() - t0

    def start_of_day(self, day: int) -> None:
        self.log = DayLog(day)
        self.days.append(self.log)
        self.last_shot_error = None
        ended_faulted = bool(self.aligner.fault)
        self.aligner.start_shift()
        if self.design.routine_inspection:
            self.inspect()  # the status quo's morning check of the optics
        self.calibrate_cameras()
        if self.design.energy_cross_cal:
            last = self.energy_cals[-1].day if self.energy_cals else None
            if last is None or day - last >= int(self.cfg["energy"]["cross_cal_every_days"]):
                self.cross_calibrate_energy()
        if self.design.alignment == "manual":
            self.manual_align("start of shift")
            return
        if self.design.matrix == "measured" and (self.aligner.cal.source == "nominal" or ended_faulted):
            if self.measure_low(int(self.cfg["alignment"]["frames_per_measure"])).lost:
                # only when the beam is off a camera: the commissioning matrix is good enough to find it
                self.align("find the beam", iterations=4)
            t0 = self.now()
            cal = self.aligner.calibrate(day)
            self.store.put_calibration("matrix", day, self.now(), cal.summary())
            self.log.calibration_seconds += self.now() - t0
            if self.aligner.fault:
                self.alert("actuator", "critical", self.aligner.fault)
        self.align("start of shift")

    # ------------------------------------------------------------------ alignment

    def _record_alignment(self, res: AlignResult) -> None:
        self.alignments.append(res)
        self.store.put_alignment(res.day, res.started_s, res.summary())
        self.bus.publish("lbp/alignment", AlignmentMsg(res.day, res.started_s, res.reason, res.iterations, res.converged, res.seconds))
        if self.log:
            self.log.align_seconds += res.seconds
            self.log.alignments += 1
        if res.refreshed:
            self.store.put_calibration("matrix", res.day, self.now(), self.aligner.cal.summary())
        if res.fault:
            self.alert("actuator", "critical", res.fault)
        self.shots_since_align = 0

    def align(self, reason: str, iterations: int | None = None) -> AlignResult:
        res = self.aligner.align(reason, self.day(), iterations)
        self._record_alignment(res)
        return res

    def manual_align(self, reason: str) -> AlignResult:
        start = self.clock.now()  # type: ignore[attr-defined]
        res = self.aligner.align(reason, self.day(), int(self.cfg["manual"]["iterations"]), count_failures=False)
        budget = float(self.cfg["manual"]["align_minutes"]) * 60.0
        spent = self.clock.now() - start  # type: ignore[attr-defined]
        if spent < budget:
            self.clock.sleep(budget - spent)  # type: ignore[attr-defined]
        res.seconds = self.clock.now() - start  # type: ignore[attr-defined]
        res.manual = True
        self._record_alignment(res)
        return res

    # ------------------------------------------------------------------ the shot cycle

    def _inputs(self, nf: Metrics | None, purpose: str = "experiment", pre: Measurement | None = None) -> ShotInputs:
        target = float(self.cfg["energy"]["target_j"])
        faults = tuple(name for name, d in self.devices.items() if d.health.faulted)
        try:
            temp = self.lcu.diode_temp_c()
        except DeviceTimeout:
            temp = float("nan")
        usable = _finite(nf)
        return ShotInputs(
            energy_target_j=target,
            pump=self.pump(),
            device_faults=faults,
            alignment_fault=self.aligner.fault,
            diode_temp_c=temp,
            profile_peak_fraction=nf.peak_fraction if usable and nf is not None else None,
            profile_saturated=bool(nf is not None and nf.saturated > 0 and self.design.auto_exposure),
            energy_cal_valid=self._energy_traceable(),
            beam_lost=bool(pre is not None and pre.lost),
            alignment_error=self.aligner.weighted(pre.error) if pre is not None and not pre.lost and self.design.preshot_pulse else None,
        )

    def pump(self) -> float:
        e = self.cfg["energy"]
        return float(min(float(e["pump_max"]), max(0.0, float(e["target_j"]) / self.gain)))

    def _decide(self, inputs: ShotInputs) -> Decision:
        decision = evaluate(inputs, self.cfg, self.design.fluence_interlock)
        did = f"d-{next(self._decision_ids):06d}"
        self.decisions.append((did, self.day(), self.now(), inputs, decision))
        self.store.put_decision(did, self.day(), self.now(), decision.as_dict())
        self.bus.publish(
            "lbp/interlock",
            InterlockMsg(
                did, self.day(), self.now(), decision.permit, "; ".join(decision.reasons), decision.predicted_fluence_j_cm2 or 0.0
            ),
        )
        if self.on_decision:
            self.on_decision(inputs, decision)
        return decision

    def _handle_block(self, decision: Decision) -> None:
        if self.log:
            self.log.blocked += 1
        if decision.action == "inspect":
            self.alert("fluence", "critical", decision.reasons[-1])
            self.inspect()
        elif decision.action == "service":
            self.alert("service", "critical", "; ".join(decision.reasons))

    def inspect(self) -> str:
        found = self.lcu.inspect()
        if self.log:
            self.log.inspections += 1
        text = {"damage": "inspection found a damaged optic; it was replaced", "hotspot": "inspection found and cleaned a hot spot"}
        self.alert("inspection", "critical" if found == "damage" else "info", text.get(found, "inspection found nothing"))
        self.last_nf = None
        return found

    def _fire(self, inputs: ShotInputs, decision: Decision, purpose: str, pre: Measurement | None = None) -> ShotRecord | None:
        shot_id = f"S{self.day():03d}-{next(self._shot_ids):05d}"
        target = inputs.energy_target_j
        approved_by = None
        if target >= float(self.cfg["operator"]["two_person_energy_j"]):
            approved_by = self.approver.approve(shot_id, target)  # type: ignore[attr-defined]
        pump = self.pump()
        try:
            pid = self.lcu.fire_full(pump)
        except DeviceError as exc:
            self.alert("laser", "critical", str(exc))
            return None
        t_fire = self.now()
        nf, nf_img = self.frame_metrics("nf", pid, "full")
        ff, ff_img = self.frame_metrics("ff", pid, "full")
        try:
            raw = self.em.read()
        except DeviceTimeout:
            raw = None
        reported = raw * self.energy_factor() if raw is not None else None
        if reported is not None and pump > 0:
            a = float(self.cfg["energy"]["gain_ewma"])
            self.gain = (1 - a) * self.gain + a * reported / pump
        err = self.error_of(nf, ff) if _finite(nf) and _finite(ff) else np.full(4, np.nan)
        px = float(self.cfg["fluence"]["nf_mm_per_px_at_optic"])
        fluence = predicted_fluence(reported, nf.peak_fraction, px) if reported is not None and _finite(nf) else None
        cals = self._cal_ids()
        cals["approved_by"] = approved_by
        did = self.decisions[-1][0] if self.decisions else ""
        rec = ShotRecord(
            shot_id=shot_id,
            pulse_id=pid,
            day=self.day(),
            t_s=t_fire,
            purpose=purpose,
            pump=pump,
            energy_target_j=target,
            energy_raw_j=raw,
            energy_reported_j=reported,
            error=[float(x) for x in err],
            nf_d4_mm=float(nf.d4x * self.cfg["reference"]["nf_mm_per_px"]) if _finite(nf) else float("nan"),
            peak_fraction=float(nf.peak_fraction) if _finite(nf) else float("nan"),
            fluence_est_j_cm2=fluence,
            predicted_fluence_j_cm2=decision.predicted_fluence_j_cm2,
            saturated=bool(nf.saturated > 0 or ff.saturated > 0),
            pre_error=[float(x) for x in pre.error] if pre is not None else None,
            calibrations=cals,
            decision_id=did,
        )
        self.shots.append(rec)
        self.store.put_shot(rec.row())
        self.store.put_frames(
            shot_id,
            self.day(),
            {"nf": nf_img, "ff": ff_img},
            {
                "nf": {"exposure": self.exposure[("nf", "full")], "camera_cal": cals["nf_camera"] or ""},
                "ff": {"exposure": self.exposure[("ff", "full")], "camera_cal": cals["ff_camera"] or ""},
            },
        )
        self.bus.publish(
            "lbp/shot",
            ShotMsg(shot_id, rec.day, rec.t_s, reported or 0.0, *[0.0 if math.isnan(x) else x for x in rec.error], fluence or 0.0),
        )
        if self._usable_profile(nf):
            self.last_nf = nf
        if not np.isnan(err).any():
            self.last_shot_error = err
        if self.log:
            self.log.fired += 1
        return rec

    def cycle(self, slot: float | None = None) -> ShotRecord | None:
        """Prepare the shot (pre-shot pulse, realignment), wait for the amplifiers if preparation was quick,
        then ask the interlocks and fire."""
        d = self.design
        pre: Measurement | None = None
        if self.aligner.fault and d.alignment == "auto":
            pass  # alignment unavailable; the interlock holds the shot
        elif d.preshot_pulse:
            pre = self.preshot()
            if d.realign == "condition" and (
                pre.lost or self.aligner.weighted(pre.error) > float(self.cfg["tolerance"]["realign_fraction"])
            ):
                self.align("pre-shot error")
                pre = self.preshot()
        if (
            d.realign == "schedule"
            and not self.aligner.fault
            and self.shots_since_align >= int(self.cfg["alignment"]["schedule_every_shots"])
        ):
            self.align("schedule")
            if d.preshot_pulse:
                pre = self.preshot()
        drifted = self.last_shot_error is not None and self.aligner.weighted(self.last_shot_error) > float(
            self.cfg["manual"]["realign_factor"]
        )
        if d.realign == "operator" and drifted:
            self.manual_align("operator saw drift")
        if pre is None and self.last_nf is None and not self.aligner.fault:
            # no profile since an inspection or a fresh start: look at the beam with a low pulse first
            pre = self.preshot()
        nf = pre.nf if pre is not None else self.last_nf
        if pre is not None and self._usable_profile(pre.nf):
            self.last_nf = pre.nf
        if slot is not None and self.now() < slot:
            self.clock.sleep(slot - self.now())  # type: ignore[attr-defined]
        inputs = self._inputs(nf, pre=pre)
        decision = self._decide(inputs)
        if not decision.permit:
            self._handle_block(decision)
            return None
        rec = self._fire(inputs, decision, "experiment", pre)
        if rec is not None:
            self.shots_since_align += 1
        return rec

    def run_day(self, day: int) -> DayLog:
        self.start_of_day(day)
        cadence = float(self.cfg["schedule"]["shot_cadence_s"])
        lead = float(self.cfg["schedule"]["preshot_lead_s"])
        length = float(self.clock.day_length())  # type: ignore[attr-defined]
        next_slot = self.now() + lead
        while True:
            now = self.now()
            if now + lead >= length:
                break
            if now < next_slot - lead:
                self.clock.sleep(next_slot - lead - now)  # type: ignore[attr-defined]
            rec = self.cycle(next_slot)
            fired_at = rec.t_s if rec is not None else self.now()
            next_slot = max(next_slot, fired_at) + cadence
        for name, dev in self.devices.items():
            h = dev.health
            self.bus.publish("lbp/health", HealthMsg(name, h.ok, h.failures, h.crc_errors, h.faulted))
        assert self.log is not None
        return self.log

    def run(self, days: int, start_day_hook: Callable[[int], None]) -> None:
        for day in range(days):
            start_day_hook(day)
            self.run_day(day)
