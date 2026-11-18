"""Automated beam alignment: measure how the four mirror axes move the beam, then steer it to the reference.

The interaction matrix maps actuator steps to (near-field x, y in mm; far-field x, y in microradians). It is
measured on the beamline, because the mounts' step sizes, cross-coupling and backlash differ from the drawings
and change with wear. Corrections are a damped least-squares solve weighted by the tolerances, so a millimetre
and a microradian count by how close each is to its limit.

Mechanics: each axis's lost motion on a change of direction (backlash) and its reverse-to-forward step ratio
are measured with the matrix; a move adds the backlash after a reversal and scales reverse steps. A move that does not do what the matrix predicts, twice in a row, triggers a fresh
measurement of the matrix. An axis that barely moves the beam is reported as stuck, and alignment stops.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from lbp.devices.drivers import Picomotor

AXES = ("M1x", "M1y", "M2x", "M2y")
_ids = itertools.count(1)


@dataclass
class Measurement:
    error: np.ndarray  # (nf x mm, nf y mm, ff x urad, ff y urad) from the reference
    lost: bool  # the beam is at the edge of a camera or missing
    nf: object | None = None  # the last near-field metrics


@dataclass
class MatrixCal:
    day: int
    matrix: np.ndarray
    backlash: np.ndarray
    reverse_ratio: np.ndarray
    source: str
    cal_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.cal_id:
            self.cal_id = f"matrix-{next(_ids):04d}"

    def summary(self) -> dict:
        return {
            "cal_id": self.cal_id,
            "day": self.day,
            "source": self.source,
            "matrix": np.round(self.matrix, 6).tolist(),
            "backlash": np.round(self.backlash, 2).tolist(),
            "reverse_ratio": np.round(self.reverse_ratio, 4).tolist(),
            "condition": float(np.linalg.cond(self.matrix)),
        }


@dataclass
class AlignResult:
    reason: str
    day: int
    started_s: float
    seconds: float
    iterations: int
    converged: bool
    final_error: list[float]
    refreshed: bool = False
    fault: str = ""
    manual: bool = False

    def summary(self) -> dict:
        return {
            "reason": self.reason,
            "day": self.day,
            "started_s": round(self.started_s, 1),
            "seconds": round(self.seconds, 1),
            "iterations": self.iterations,
            "converged": self.converged,
            "final_error": [round(x, 4) for x in self.final_error],
            "refreshed": self.refreshed,
            "fault": self.fault,
            "manual": self.manual,
        }


def nominal_matrix(cfg: dict) -> np.ndarray:
    """The commissioning matrix from the drawings: lever arms, no mount rotation, the nominal step size."""
    a = cfg["alignment"]
    step = float(a["nominal_step_urad"])
    m = np.zeros((4, 4))
    for k, lever in enumerate(a["nominal_lever_m"]):
        for j in range(2):
            col = 2 * k + j
            m[j, col] = 2.0 * lever * 1e-3 * step
            m[2 + j, col] = 2.0 * step
    return m


class Aligner:
    def __init__(self, cfg: dict, design: object, motors: Picomotor, measure: Callable[[int], Measurement], clock: object):
        self.cfg, self.design, self.motors, self.measure, self.clock = cfg, design, motors, measure, clock
        a = cfg["alignment"]
        self.a = a
        tol = cfg["tolerance"]
        self.w = np.array([1 / tol["nf_mm"], 1 / tol["nf_mm"], 1 / tol["ff_urad"], 1 / tol["ff_urad"]])
        self.nominal = nominal_matrix(cfg)
        self.cal = MatrixCal(-1, self.nominal.copy(), np.zeros(4), np.ones(4), "nominal")
        self.last_dir = np.ones(4, dtype=int)  # mounts are delivered loaded forward
        self.travel = np.zeros(4, dtype=int)  # steps commanded since the shift started
        self.failed = 0
        self.fault = ""
        self.history: list[MatrixCal] = []

    # ------------------------------------------------------------------ moves

    def start_shift(self) -> None:
        """A new shift: travel is counted from here, and a fault from the last shift is retried."""
        self.travel[:] = 0
        self.failed = 0
        self.fault = ""

    def move(self, axis: int, steps: int) -> None:
        steps = int(steps)
        if steps == 0 or self.fault:
            return
        limit = int(self.a["travel_limit_steps"])
        if abs(self.travel[axis] + steps) > limit:
            self.fault = f"alignment reached the travel limit on {AXES[axis]}"
            return
        sign = 1 if steps > 0 else -1
        cmd = steps
        if self.design.backlash_compensation:  # type: ignore[attr-defined]
            # the matrix is per forward step; a reverse step is r times as long
            if sign < 0 and self.cal.reverse_ratio[axis] > 0:
                cmd = int(round(steps / self.cal.reverse_ratio[axis]))
            if sign != self.last_dir[axis]:
                cmd += sign * int(round(self.cal.backlash[axis]))
        self.motors.move(axis, cmd)
        self.travel[axis] += cmd
        self.last_dir[axis] = sign

    def _raw(self, axis: int, steps: int) -> None:
        self.motors.move(axis, int(steps))
        self.travel[axis] += int(steps)
        if steps:
            self.last_dir[axis] = 1 if steps > 0 else -1

    def weighted(self, e: np.ndarray) -> float:
        return float(np.max(np.abs(e * self.w)))

    # ------------------------------------------------------------------ the interaction matrix

    def calibrate(self, day: int) -> MatrixCal:
        s = int(self.a["poke_steps"])
        k = int(self.a["frames_per_measure"]) * 2
        cols, backlash, ratio = np.zeros((4, 4)), np.zeros(4), np.ones(4)
        stuck = []
        lost = False
        measure = self.measure

        def meas(k: int) -> Measurement:
            nonlocal lost
            m = measure(k)
            lost = lost or m.lost
            return m

        for axis in range(4):
            if self.design.backlash_compensation:  # type: ignore[attr-defined]
                # load the drive forward, measure forward, then twice backward to see the lost motion
                self._raw(axis, -s)
                self._raw(axis, +s)
                p0 = meas(k).error
                self._raw(axis, +s)
                p1 = meas(k).error
                f = (p1 - p0) / s
                self._raw(axis, -s)
                p2 = meas(k).error
                self._raw(axis, -s)
                p3 = meas(k).error
                fw = f * self.w
                norm2 = float(fw @ fw)
                r = float(-((p3 - p2) * self.w) @ fw / (s * norm2)) if norm2 > 0 else 1.0
                lo, hi = self.a["reverse_ratio_bounds"]
                r = float(np.clip(r, lo, hi))
                play = s - float(-((p2 - p1) * self.w) @ fw / (r * norm2)) if norm2 > 0 else 0.0
                play = float(np.clip(play, 0.0, s))
                # return to where the axis started, approaching forward: the first `play` steps take up the
                # play, then (2s - play) * r - s forward steps undo the net backward travel
                self._raw(axis, max(0, int(round(play + (2 * s - play) * r - s))))
                cols[:, axis], backlash[axis], ratio[axis] = f, play, r
            else:
                # the textbook symmetric poke, which backlash quietly corrupts
                self._raw(axis, +s)
                pp = meas(k).error
                self._raw(axis, -2 * s)
                pm = meas(k).error
                self._raw(axis, +s)
                cols[:, axis] = (pp - pm) / (2 * s)
            nominal = float(np.linalg.norm(self.nominal[:, axis] * self.w))
            if float(np.linalg.norm(cols[:, axis] * self.w)) < float(self.a["stuck_fraction"]) * nominal:
                stuck.append(AXES[axis])
        if self.design.backlash_compensation and not lost and not stuck:
            cols[0:2] = self._walk_near_field(cols, meas, k)
        if lost:
            return self.cal  # the beam left a camera during the pokes: keep the matrix we had
        if stuck:
            self.fault = f"actuator not moving the beam: {', '.join(stuck)}"
            return self.cal
        self.fault = ""
        self.cal = MatrixCal(day, cols, backlash, ratio, "measured")
        self.history.append(self.cal)
        return self.cal

    def _walk_near_field(self, cols: np.ndarray, meas: Callable[[int], Measurement], k: int) -> np.ndarray:
        """Re-measure the near-field rows along the centring modes.

        A single-axis poke small enough to keep the far-field spot on its camera barely moves the near field,
        so those rows come out noisy, and a noisy near-field row makes the two mirrors fight each other. The
        moves that leave the pointing unchanged (the null space of the far-field rows: "walking" the beam
        with both mirrors) can be large, so the near-field response along them is measured to a few per cent.
        Along the pointing directions the poke estimate is kept.
        """
        ff = cols[2:4, :]
        _, _, vt = np.linalg.svd(ff)
        null, rows = vt[2:].T, vt[:2].T
        cap = float(self.a["max_step_command"])
        basis, response = [], []
        walk_cap = min(cap, float(self.a["walk_max_steps"]))
        for i in range(2):
            v = null[:, i]
            pred = float(np.linalg.norm(cols[0:2] @ v))
            raw = v * float(self.a["walk_mm"]) / max(pred, 1e-9)
            raw = raw * min(1.0, walk_cap / max(float(np.max(np.abs(raw))), 1e-9))
            steps = np.rint(raw).astype(int)
            # walk out to +steps and -steps and back: twice the baseline, and drift cancels to first order
            for axis, n in enumerate(steps):
                self.move(axis, int(n))
            q_plus = meas(k).error
            for axis, n in enumerate(steps):
                self.move(axis, -2 * int(n))
            q_minus = meas(k).error
            for axis, n in enumerate(steps):
                self.move(axis, int(n))
            basis.append(steps.astype(float))
            response.append(((q_plus - q_minus) / 2.0)[0:2])
        for j in range(2):
            basis.append(rows[:, j])
            response.append(cols[0:2] @ rows[:, j])
        a = np.column_stack(basis)
        b = np.column_stack(response)
        if abs(np.linalg.det(a)) < 1e-9:
            return cols[0:2]
        return b @ np.linalg.inv(a)

    # ------------------------------------------------------------------ closing the loop

    def solve(self, e: np.ndarray) -> np.ndarray:
        wm = self.cal.matrix * self.w[:, None]
        delta, *_ = np.linalg.lstsq(wm, -(e * self.w), rcond=None)
        delta = float(self.a["damping"]) * delta
        cap = float(self.a["max_steps_per_iteration"] if self.cal.source == "measured" else self.a["max_steps_uncalibrated"])
        biggest = float(np.max(np.abs(delta)))
        if biggest > cap:
            delta = delta * (cap / biggest)  # keep the direction, shorten the step
        return np.rint(delta).astype(int)

    def align(self, reason: str, day: int, iterations: int | None = None, count_failures: bool = True) -> AlignResult:
        start = self.clock.now()  # type: ignore[attr-defined]
        target = float(self.cfg["tolerance"]["align_target_fraction"])
        k = int(self.a["frames_per_measure"])
        max_it = int(iterations if iterations is not None else self.a["max_iterations"])
        refreshed = False
        gain = 1.0
        strikes = 0
        prev_e: np.ndarray | None = None
        prev_delta: np.ndarray | None = None
        m = self.measure(k)
        it = 0
        while it < max_it:
            it += 1
            if self.fault:
                break
            if m.lost and prev_delta is not None:
                # the last correction took the beam off a camera: undo it and continue with half the gain
                for axis, n in enumerate(prev_delta.astype(int)):
                    self.move(axis, -int(n))
                gain *= 0.5
                prev_e, prev_delta = None, None
                m = self.measure(k)
                continue
            if m.lost:
                # coarse: steer with the commissioning matrix; a centroid at the edge still points the right way
                wm = self.nominal * self.w[:, None]
                delta, *_ = np.linalg.lstsq(wm, -(m.error * self.w), rcond=None)
                delta = 0.5 * delta
                cap = float(self.a["max_steps_uncalibrated"])
                if float(np.max(np.abs(delta))) > cap:
                    delta = delta * cap / float(np.max(np.abs(delta)))
                for axis, n in enumerate(np.rint(delta).astype(int)):
                    self.move(axis, int(n))
                prev_e, prev_delta = None, None
                m = self.measure(k)
                continue
            if self.weighted(m.error) <= target:
                break
            if prev_e is not None and prev_delta is not None and self.design.matrix_refresh:  # type: ignore[attr-defined]
                predicted = self.cal.matrix @ prev_delta
                observed = m.error - prev_e
                denom = float(np.linalg.norm(predicted * self.w))
                if denom >= float(self.a["mismatch_min_move"]):
                    ratio = float(np.linalg.norm((observed - predicted) * self.w)) / denom
                    strikes = strikes + 1 if ratio > float(self.a["mismatch_ratio"]) else 0
                if strikes >= int(self.a["mismatch_strikes"]):
                    self.calibrate(day)
                    refreshed = True
                    strikes = 0
                    if self.fault:
                        break
                    m = self.measure(k)
                    prev_e, prev_delta = None, None
                    continue
            delta = np.rint(self.solve(m.error) * gain).astype(int)
            for axis, n in enumerate(delta):
                self.move(axis, int(n))
            prev_e, prev_delta = m.error, delta.astype(float)
            m = self.measure(k)
        converged = (not m.lost) and self.weighted(m.error) <= target and not self.fault
        # an alignment that ends inside tolerance is not a failure, even if it missed the tighter target
        usable = (not m.lost) and self.weighted(m.error) <= 1.0 and not self.fault
        if count_failures:
            self.failed = 0 if usable else self.failed + 1
        if count_failures and self.failed >= int(self.a["failed_alignments_fault"]) and not self.fault:
            self.fault = f"alignment did not converge {self.failed} times in a row"
        return AlignResult(
            reason=reason,
            day=day,
            started_s=start,
            seconds=self.clock.now() - start,  # type: ignore[attr-defined]
            iterations=it,
            converged=converged,
            final_error=[float(x) for x in m.error],
            refreshed=refreshed,
            fault=self.fault,
        )
