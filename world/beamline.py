"""The simulated beamline and its hidden truth.

Two motorised mirrors steer a diode-pumped laser beam onto the aperture of an amplifier (near field, NF) and
into the direction of the target chamber (far field, FF). The table drifts, the mounts have backlash, the
cameras have background, hot pixels and a full scale, the pyroelectric energy meter loses sensitivity, and dust
can put a hot spot on an optic. A full shot whose peak fluence exceeds the damage threshold damages the optic.

Nothing in lbp/ imports this module. The platform sees the beamline only through the device emulators in
world/emulators.py, which speak the same protocols a real controller, camera or meter would.

Same luck for every design: every random draw comes from a stream keyed by (seed, stream name, day, time), so
two designs that fire at the same moment see the same jitter, and the drift, hot spots, hot pixels and wear
are fixed by the seed, whatever the platform does.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np

AXES = ("M1x", "M1y", "M2x", "M2y")
GRID_STEP_S = 10.0


def _key(*parts: object) -> int:
    digest = hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def stream(seed: int, name: str, *index: object) -> np.random.Generator:
    """A random stream that depends only on the seed, its name and its index."""
    return np.random.default_rng([seed, _key(name, *index)])


@dataclass
class Pulse:
    pulse_id: int
    kind: str  # "low" (front end only) or "full"
    day: int
    t_s: float
    pump: float
    energy_j: float
    nf_mm: np.ndarray  # true beam centre on the amplifier aperture
    ff_urad: np.ndarray  # true pointing error at the target chamber
    peak_fluence_j_cm2: float
    clipped_fraction: float
    damaged: bool = False
    hotspot: bool = False
    meter_raw_j: float = 0.0
    reference_j: float | None = None


@dataclass
class Event:
    day: int
    t_s: float
    kind: str
    detail: str


@dataclass
class Camera:
    """A camera's fixed defects: background shape and hot pixels."""

    name: str
    size: int
    full_scale: int
    dark_offset: float
    gradient: float
    read_noise: float
    photons_per_count: float
    peak_counts: float
    hot: dict[tuple[int, int], float] = field(default_factory=dict)
    gain_steps: list[tuple[int, float]] = field(default_factory=list)
    gradient_dir: tuple[float, float] = (1.0, 0.0)

    def gain(self, day: int) -> float:
        g = 1.0
        for d, factor in self.gain_steps:
            if day >= d:
                g *= factor
        return g

    def background(self) -> np.ndarray:
        n = self.size
        ramp = (np.arange(n) - (n - 1) / 2) / (n - 1)
        gx, gy = self.gradient_dir
        bg = self.dark_offset + self.gradient * (gx * ramp[None, :] + gy * ramp[:, None])
        return bg

    def render(self, signal: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        frame = self.background() + signal
        shot = np.sqrt(np.clip(signal, 0, None) / self.photons_per_count)
        frame = frame + shot * rng.standard_normal(signal.shape) + self.read_noise * rng.standard_normal(signal.shape)
        for (r, c), value in self.hot.items():
            frame[r, c] += value
        return np.clip(np.rint(frame), 0, self.full_scale).astype(np.uint16)


class Beamline:
    def __init__(self, cfg: dict, seed: int | None = None):
        self.cfg = cfg
        self.seed = int(seed if seed is not None else cfg["campaign"]["seed"])
        c = cfg["campaign"]
        self.days = int(c["days"])
        self.day_s = float(c["day_minutes"]) * 60.0
        o, d, b = cfg["optics"], cfg["drift"], cfg["beam"]
        self.optics, self.drift, self.beam = o, d, b
        self.timing = cfg["timing"]

        # Interaction of the four mirror axes with (NF x, NF y, FF x, FF y): the truth the platform must measure.
        self.matrix = self._true_matrix()
        self.theta = np.zeros(4)  # true mirror angles, microradians
        self.play = np.array(o["backlash_steps"], dtype=float)  # every drive starts loaded forward
        self.backlash = np.array(o["backlash_steps"], dtype=float)
        self.step = np.array(o["step_urad"], dtype=float)
        self.reverse = np.array(o["reverse_ratio"], dtype=float)
        self.commanded = np.zeros(4, dtype=int)

        self.nf_cam = self._camera("nf_camera")
        self.ff_cam = self._camera("ff_camera")
        self.day = -1
        self.t = 0.0
        self.pulse_count = 0
        self.pulses: list[Pulse] = []
        self.events: list[Event] = []
        self.damage_sites: list[list[float]] = []  # x mm, y mm, modulation level
        self.hotspot_active = False
        self.hotspot_at: tuple[float, float] = (0.0, 0.0)
        self.hotspot_start = math.inf
        self.reference_inserted = False
        self._profiles: dict[int, np.ndarray] = {}
        self.reference_bias = float(stream(self.seed, "ref-bias").normal(0, cfg["reference_meter"]["uncertainty_k2"] / 2))
        self._day_offsets = self._overnight_offsets()
        self._walk: np.ndarray | None = None
        self._warm_dir = np.zeros(4)
        self._temp_offset = 0.0
        self._temp_walk: np.ndarray | None = None

    # ------------------------------------------------------------------ construction

    def _true_matrix(self) -> np.ndarray:
        o = self.optics
        m = np.zeros((4, 4))
        for k, (lever, rot) in enumerate(zip(o["lever_m"], o["mount_rotation_deg"], strict=True)):
            phi = math.radians(rot)
            r = np.array([[math.cos(phi), -math.sin(phi)], [math.sin(phi), math.cos(phi)]])
            cols = slice(2 * k, 2 * k + 2)
            m[0:2, cols] = 2.0 * lever * 1e-3 * r  # mm of near-field shift per microradian
            m[2:4, cols] = 2.0 * r  # microradians of pointing per microradian
        return m

    def _camera(self, name: str) -> Camera:
        k = self.cfg[name]
        rng = stream(self.seed, f"{name}-defects")
        angle = rng.uniform(0, 2 * math.pi)
        cam = Camera(
            name=name,
            size=int(k["size"]),
            full_scale=int(k["full_scale"]),
            dark_offset=float(k["dark_offset"]),
            gradient=float(k["gradient"]),
            read_noise=float(k["read_noise"]),
            photons_per_count=float(k["photons_per_count"]),
            peak_counts=float(k["peak_counts"]),
            gain_steps=[(int(dd), float(f)) for dd, f in k.get("gain_steps", [])],
            gradient_dir=(math.cos(angle), math.sin(angle)),
        )
        return cam

    def _grow_hot_pixels(self, cam: Camera, name: str, day: int) -> None:
        k = self.cfg[name]
        target = int(k["hot_pixels"]) + int(k["hot_pixel_growth_per_day"]) * day
        rng = stream(self.seed, f"{name}-hot", day)
        while len(cam.hot) < target:
            r, c = int(rng.integers(0, cam.size)), int(rng.integers(0, cam.size))
            cam.hot[(r, c)] = float(rng.uniform(600, 4000))

    def _overnight_offsets(self) -> np.ndarray:
        d = self.drift
        rng = stream(self.seed, "overnight")
        offsets = np.zeros((self.days + 1, 4))
        start = np.array([rng.normal(0, 1.2), rng.normal(0, 1.2), rng.normal(0, 8), rng.normal(0, 8)])
        offsets[0] = start
        sd = np.array([d["nf_overnight_mm"], d["nf_overnight_mm"], d["ff_overnight_urad"], d["ff_overnight_urad"]])
        for day in range(1, self.days + 1):
            offsets[day] = offsets[day - 1] + rng.normal(0, 1, 4) * sd / math.sqrt(2)
        return offsets

    # ------------------------------------------------------------------ time

    def start_day(self, day: int) -> None:
        self.day = day
        self.t = 0.0
        d = self.drift
        n = int(self.day_s / GRID_STEP_S) + 2
        rng = stream(self.seed, "walk", day)
        scale = math.sqrt(GRID_STEP_S / float(self.cfg["campaign"]["shot_cadence_s"]))
        sd = np.array([d["nf_walk_mm"], d["nf_walk_mm"], d["ff_walk_urad"], d["ff_walk_urad"]]) * scale
        self._walk = np.cumsum(rng.normal(0, 1, (n, 4)) * sd, axis=0)
        wd = stream(self.seed, "warm-dir", day).normal(0, 1, 4)
        self._warm_dir = np.array([wd[0], wd[1], wd[2], wd[3]]) / np.array(
            [np.hypot(wd[0], wd[1]), np.hypot(wd[0], wd[1]), np.hypot(wd[2], wd[3]), np.hypot(wd[2], wd[3])]
        )
        b = self.beam
        self._temp_offset = float(stream(self.seed, "diode-day", day).normal(0, b["diode_temp_day_sd_k"]))
        self._temp_walk = np.cumsum(stream(self.seed, "diode-walk", day).normal(0, b["diode_temp_walk_k"], n))
        self._grow_hot_pixels(self.nf_cam, "nf_camera", day)
        self._grow_hot_pixels(self.ff_cam, "ff_camera", day)
        hs = self.cfg["hotspot"]
        self.hotspot_active = False
        self.hotspot_start = math.inf
        if day in hs["days"]:
            rng = stream(self.seed, "hotspot", day)
            self.hotspot_start = float(rng.uniform(0.2, 0.6) * self.day_s)
            ang, rad = rng.uniform(0, 2 * math.pi), rng.uniform(3, 9)
            self.hotspot_at = (rad * math.cos(ang), rad * math.sin(ang))
        for w in self.optics.get("wear", []):
            if int(w["day"]) == day:
                self.step[int(w["axis"])] *= float(w["factor"])
                self.reverse[int(w["axis"])] *= 1.0
                self.events.append(Event(day, 0.0, "wear", f"{AXES[int(w['axis'])]} step x{w['factor']}"))
        for name, cam in (("nf_camera", self.nf_cam), ("ff_camera", self.ff_cam)):
            for dd, f in cam.gain_steps:
                if dd == day:
                    self.events.append(Event(day, 0.0, "camera-gain", f"{name} gain x{f}"))

    def advance(self, seconds: float) -> None:
        self.t += max(0.0, float(seconds))
        if not self.hotspot_active and self.t >= self.hotspot_start:
            self.hotspot_active = True
            self.hotspot_start = math.inf
            self.events.append(Event(self.day, self.t, "hotspot", f"at {self.hotspot_at[0]:.1f},{self.hotspot_at[1]:.1f} mm"))

    def _grid(self, arr: np.ndarray | None) -> np.ndarray:
        assert arr is not None
        i = min(int(self.t / GRID_STEP_S), len(arr) - 1)
        return arr[i]

    def diode_temp_c(self) -> float:
        return float(self.beam["diode_temp_c"] + self._temp_offset + self._grid(self._temp_walk))

    # ------------------------------------------------------------------ optics

    def beam_position(self) -> np.ndarray:
        """True (NF x mm, NF y mm, FF x urad, FF y urad) at this moment, without shot-to-shot jitter."""
        d = self.drift
        warm = 1.0 - math.exp(-(self.t / 60.0) / d["warmup_tau_min"])
        amp = np.array([d["warmup_nf_mm"], d["warmup_nf_mm"], d["warmup_ff_urad"], d["warmup_ff_urad"]])
        return self.matrix @ self.theta + self._day_offsets[self.day] + self._grid(self._walk) + warm * amp * self._warm_dir

    def move(self, axis: int, steps: int) -> float:
        """Drive one actuator; returns the time it took. The controller counts what was commanded."""
        self.commanded[axis] += steps
        rng = stream(self.seed, "move", self.day, round(self.t * 10), axis, self.commanded[axis])
        duration = abs(steps) / float(self.timing["steps_per_s"]) + float(self.timing["move_settle_s"])
        if steps == 0:
            return 0.0
        if rng.random() < float(self.optics["missed_move_prob"]):
            self.events.append(Event(self.day, self.t, "missed-move", f"{AXES[axis]} {steps}"))
            self.advance(duration)
            return duration
        b = self.backlash[axis]
        n = abs(steps)
        if steps > 0:
            take = min(n, b - self.play[axis])
            self.play[axis] += take
            moved = (n - take) * self.step[axis]
        else:
            take = min(n, self.play[axis])
            self.play[axis] -= take
            moved = -(n - take) * self.step[axis] * self.reverse[axis]
        self.theta[axis] += moved * (1.0 + rng.normal(0, float(self.optics["step_jitter"])))
        self.advance(duration)
        return duration

    # ------------------------------------------------------------------ the beam on the optic

    def _optic_grid(self) -> tuple[np.ndarray, np.ndarray]:
        n = self.nf_cam.size
        mm = float(self.cfg["nf_camera"]["mm_per_px"])
        coords = (np.arange(n) - (n - 1) / 2) * mm
        return np.meshgrid(coords, coords)

    def _modulation(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        mod = np.ones_like(x)
        hs = self.cfg["hotspot"]
        if self.hotspot_active:
            hx, hy = self.hotspot_at
            mod *= 1.0 + (hs["peak_gain"] - 1.0) * np.exp(-((x - hx) ** 2 + (y - hy) ** 2) / (2 * hs["radius_mm"] ** 2))
        for sx, sy, level in self.damage_sites:
            mod *= 1.0 + level * np.exp(-((x - sx) ** 2 + (y - sy) ** 2) / (2 * 1.5**2))
        return mod

    def profile(self, centre_mm: np.ndarray) -> tuple[np.ndarray, float]:
        """Normalised near-field intensity on the camera grid (flat top = 1) and the clipped energy fraction."""
        x, y = self._optic_grid()
        b = self.beam
        r = np.hypot(x - centre_mm[0], y - centre_mm[1])
        sg = np.exp(-2.0 * (r / b["radius_mm"]) ** (2 * b["order"]))
        sg = sg * self._modulation(x, y)
        inside = np.hypot(x, y) <= b["aperture_mm"]
        total = sg.sum()
        clipped = float(1.0 - sg[inside].sum() / total) if total > 0 else 0.0
        out = np.where(inside, sg, 0.0)
        if clipped > 0.002:
            # diffraction from the hard edge raises the intensity ripple behind the aperture
            out = out * (1.0 + min(0.5, 4.0 * clipped) * np.exp(-((r - b["radius_mm"]) ** 2) / 8.0))
        return out, clipped

    def fire(self, kind: str, pump: float = 0.0) -> Pulse:
        if kind not in ("low", "full"):
            raise ValueError(kind)
        b = self.beam
        rng = stream(self.seed, "pulse", self.day, round(self.t * 10), kind)
        pos = self.beam_position()
        jit = np.array(
            [
                rng.normal(0, self.drift["nf_jitter_mm"]),
                rng.normal(0, self.drift["nf_jitter_mm"]),
                rng.normal(0, self.drift["ff_jitter_urad"]),
                rng.normal(0, self.drift["ff_jitter_urad"]),
            ]
        )
        pos = pos + jit
        prof, clipped = self.profile(pos[:2])
        if kind == "full":
            g0 = b["nominal_energy_j"] / 0.8
            gain = g0 * (1.0 + b["gain_per_kelvin"] * (self.diode_temp_c() - b["diode_temp_c"]))
            energy = max(0.0, pump) * gain * (1.0 + rng.normal(0, b["energy_jitter"]))
        else:
            energy = b["nominal_energy_j"] * b["low_pulse_fraction"] * (1.0 + rng.normal(0, b["energy_jitter"]))
        energy *= 1.0 - clipped
        mm = float(self.cfg["nf_camera"]["mm_per_px"])
        px_area_cm2 = (mm / 10.0) ** 2
        peak = float(energy * prof.max() / prof.sum() / px_area_cm2) if prof.sum() > 0 else 0.0
        self.pulse_count += 1
        p = Pulse(
            pulse_id=self.pulse_count,
            kind=kind,
            day=self.day,
            t_s=self.t,
            pump=pump,
            energy_j=energy,
            nf_mm=pos[:2].copy(),
            ff_urad=pos[2:].copy(),
            peak_fluence_j_cm2=peak,
            clipped_fraction=clipped,
            hotspot=self.hotspot_active,
        )
        self._profiles[p.pulse_id] = prof  # the cameras image recent pulses; old profiles are dropped
        while len(self._profiles) > 16:
            self._profiles.pop(next(iter(self._profiles)))
        if kind == "full" and peak > b["damage_fluence_j_cm2"]:
            p.damaged = True
            iy, ix = np.unravel_index(int(np.argmax(prof)), prof.shape)
            x, y = self._optic_grid()
            self._grow_damage(float(x[iy, ix]), float(y[iy, ix]))
            self.events.append(Event(self.day, self.t, "damage", f"pulse {p.pulse_id} peak {peak:.2f} J/cm2"))
        em = self.cfg["energy_meter"]
        factor = em["vendor_factor"] * (1.0 + em["drift_per_day"] * (self.day + self.t / self.day_s))
        p.meter_raw_j = energy * factor * (1.0 + rng.normal(0, em["noise"]))
        if self.reference_inserted:
            rm = self.cfg["reference_meter"]
            p.reference_j = energy * (1.0 + self.reference_bias) * (1.0 + rng.normal(0, rm["noise"]))
        self.pulses.append(p)
        self.advance(1.0)
        return p

    def _grow_damage(self, x: float, y: float) -> None:
        """A damage site grows with every shot that exceeds the threshold on it, up to a saturation level."""
        dm = self.cfg["damage"]
        for site in self.damage_sites:
            if math.hypot(site[0] - x, site[1] - y) < 2.5:
                site[2] = min(float(dm["max_level"]), site[2] + float(dm["growth"]))
                return
        self.damage_sites.append([x, y, float(dm["growth"])])

    # ------------------------------------------------------------------ cameras

    def nf_image(self, pulse: Pulse | None, exposure: float) -> np.ndarray:
        cam = self.nf_cam
        rng = stream(self.seed, "nf-frame", self.day, round(self.t * 10), pulse.pulse_id if pulse else 0)
        signal = np.zeros((cam.size, cam.size))
        if pulse is not None:
            b = self.beam
            ref = b["nominal_energy_j"] * (b["low_pulse_fraction"] if pulse.kind == "low" else 1.0)
            signal = self._profiles[pulse.pulse_id] * cam.peak_counts * exposure * cam.gain(self.day) * pulse.energy_j / ref
        self.advance(float(self.timing["frame_s"]) * 0.2)
        return cam.render(signal, rng)

    def ff_image(self, pulse: Pulse | None, exposure: float) -> np.ndarray:
        cam = self.ff_cam
        k = self.cfg["ff_camera"]
        rng = stream(self.seed, "ff-frame", self.day, round(self.t * 10), pulse.pulse_id if pulse else 0)
        signal = np.zeros((cam.size, cam.size))
        if pulse is not None:
            b = self.beam
            ref = b["nominal_energy_j"] * (b["low_pulse_fraction"] if pulse.kind == "low" else 1.0)
            n = cam.size
            c = (n - 1) / 2
            x0 = c + pulse.ff_urad[0] / k["urad_per_px"]
            y0 = c + pulse.ff_urad[1] / k["urad_per_px"]
            yy, xx = np.mgrid[0:n, 0:n]
            w = k["spot_radius_px"]
            spot = np.exp(-2.0 * ((xx - x0) ** 2 + (yy - y0) ** 2) / w**2)
            signal = spot * cam.peak_counts * exposure * cam.gain(self.day) * pulse.energy_j / ref
        self.advance(float(self.timing["frame_s"]) * 0.2)
        return cam.render(signal, rng)

    # ------------------------------------------------------------------ service

    def inspect_optics(self) -> str:
        """An inspection takes the beamline down. A damaged optic is replaced (hours); a hot spot is cleaned;
        otherwise the check is short. Returns "damage", "hotspot" or "clean"."""
        if self.damage_sites:
            self.damage_sites = []
            self.hotspot_active = False
            self.events.append(Event(self.day, self.t, "inspection", "damaged optic replaced"))
            self.advance(float(self.cfg["damage"]["replace_hours"]) * 3600.0)
            return "damage"
        if self.hotspot_active:
            self.hotspot_active = False
            self.hotspot_start = math.inf
            self.events.append(Event(self.day, self.t, "inspection", "hot spot cleaned"))
            self.advance(float(self.cfg["hotspot"]["cleaning_minutes"]) * 60.0)
            return "hotspot"
        self.events.append(Event(self.day, self.t, "inspection", "nothing found"))
        self.advance(float(self.cfg["hotspot"]["check_minutes"]) * 60.0)
        return "clean"

    def reference_due_day(self) -> int:
        return int(self.cfg["reference_meter"]["certificate_due_day"])
