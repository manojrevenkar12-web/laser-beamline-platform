"""Beam diagnostics on camera frames: centroid, ISO 11146 widths, peak fraction and saturation.

`analyze` is the reference implementation in NumPy. `lbp.diagnostics.native` runs the same algorithm in C++
(cpp/beamcore); tests/test_beamcore.py checks that the two agree on random frames.

ISO 11146 path (the platform):
  1. subtract the dark frame (mean of dark frames at the same exposure)
  2. replace hot pixels by the median of their unmasked 8-neighbours
  3. subtract the residual baseline, the mean of a ring at the frame border (ISO 11146-3)
  4. first and second moments, iterated over a rectangle of three times the beam widths around the centroid
     until the widths change by less than the tolerance (ISO 11146-2)
  5. the peak is the largest 3 x 3 mean inside the integration area, so one noisy pixel is not the peak

Naive path (the status quo in many labs): centroid of the raw pixels whose smoothed value is above a share of
the smoothed maximum, with no dark frame or baseline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class Options:
    analysis: str = "iso"
    background: bool = True
    hot_pixel_mask: bool = True
    iso_aperture: bool = True
    aperture_factor: float = 3.0
    max_iterations: int = 10
    tolerance: float = 0.01
    ring_px: int = 4
    naive_threshold: float = 0.5
    full_scale: int = 4095
    edge_margin_px: int = 2

    @classmethod
    def from_config(cls, cam: dict, design: object | None = None) -> Options:
        kw = dict(
            aperture_factor=cam["iso_aperture_factor"],
            max_iterations=cam["iso_max_iterations"],
            tolerance=cam["iso_tolerance"],
            ring_px=cam["baseline_ring_px"],
            naive_threshold=cam["naive_threshold"],
            full_scale=cam["full_scale"],
            edge_margin_px=cam["edge_margin_px"],
        )
        if design is not None:
            kw.update(
                analysis=design.analysis,  # type: ignore[attr-defined]
                background=design.background,  # type: ignore[attr-defined]
                hot_pixel_mask=design.hot_pixel_mask,  # type: ignore[attr-defined]
                iso_aperture=design.iso_aperture,  # type: ignore[attr-defined]
            )
        return cls(**kw)


@dataclass
class Metrics:
    cx: float
    cy: float
    d4x: float
    d4y: float
    total: float
    peak: float
    peak_fraction: float
    raw_peak: float
    saturated: float
    edge: bool
    iterations: int
    converged: bool

    def as_dict(self) -> dict:
        return asdict(self)


def fix_hot_pixels(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Replace each masked pixel by the median of its unmasked 8-neighbours (0 if it has none)."""
    out = img.copy()
    h, w = img.shape
    for r, c in zip(*np.nonzero(mask), strict=True):
        vals = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                if 0 <= rr < h and 0 <= cc < w and not mask[rr, cc]:
                    vals.append(img[rr, cc])
        out[r, c] = float(np.median(vals)) if vals else 0.0
    return out


def saturated_share(frame: np.ndarray, full_scale: int, mask: np.ndarray | None = None) -> float:
    """Share of pixels at full scale inside a bright region: at least two of their 8 neighbours above half
    scale. An isolated hot pixel at full scale does not count, nor does a masked one; a clipped beam does."""
    at = frame >= full_scale
    if mask is not None:
        at = at & ~mask.astype(bool)
    if not at.any():
        return 0.0
    bright = (frame >= full_scale / 2).astype(np.int32)
    h, w = frame.shape
    pad = np.pad(bright, 1)
    n = np.zeros((h, w), dtype=np.int32)
    for dr in (0, 1, 2):
        for dc in (0, 1, 2):
            if dr == 1 and dc == 1:
                continue
            n += pad[dr : dr + h, dc : dc + w]
    return float((at & (n >= 2)).sum() / frame.size)


def baseline(img: np.ndarray, ring: int) -> float:
    if ring <= 0:
        return 0.0
    m = np.zeros(img.shape, dtype=bool)
    m[:ring, :] = m[-ring:, :] = True
    m[:, :ring] = m[:, -ring:] = True
    return float(img[m].mean())


def corrected(frame: np.ndarray, dark: np.ndarray | None, mask: np.ndarray | None, opt: Options) -> np.ndarray:
    img = frame.astype(np.float64)
    if opt.background and dark is not None:
        img = img - dark
    if opt.hot_pixel_mask and mask is not None and mask.any():
        img = fix_hot_pixels(img, mask)
    if opt.background:
        img = img - baseline(img, opt.ring_px)
    return img


def _moments(img: np.ndarray, r0: int, r1: int, c0: int, c1: int) -> tuple[float, float, float, float, float]:
    if r1 <= r0 or c1 <= c0:
        return 0.0, float("nan"), float("nan"), float("nan"), float("nan")
    sub = img[r0:r1, c0:c1]
    total = float(sub.sum())
    if total <= 0:
        return 0.0, float("nan"), float("nan"), float("nan"), float("nan")
    rows = np.arange(r0, r1, dtype=np.float64)[:, None]
    cols = np.arange(c0, c1, dtype=np.float64)[None, :]
    cx = float((sub * cols).sum() / total)
    cy = float((sub * rows).sum() / total)
    vx = float((sub * (cols - cx) ** 2).sum() / total)
    vy = float((sub * (rows - cy) ** 2).sum() / total)
    return total, cx, cy, vx, vy


def _box_peak(img: np.ndarray, r0: int, r1: int, c0: int, c1: int) -> float:
    """Largest mean of a 3 x 3 box whose centre lies inside the area (clipped at the frame edge)."""
    h, w = img.shape
    if r1 <= r0 or c1 <= c0:
        return 0.0
    pad = np.pad(img, 1, mode="edge")
    acc = np.zeros_like(img)
    for dr in (0, 1, 2):
        for dc in (0, 1, 2):
            acc += pad[dr : dr + h, dc : dc + w]
    return float((acc[r0:r1, c0:c1] / 9.0).max())


def _window(cx: float, cy: float, vx: float, vy: float, factor: float, h: int, w: int) -> tuple[int, int, int, int]:
    hx = factor * 2.0 * np.sqrt(max(vx, 0.0))  # half of three times the D4sigma width
    hy = factor * 2.0 * np.sqrt(max(vy, 0.0))
    c0, c1 = int(np.floor(cx - hx)), int(np.ceil(cx + hx)) + 1
    r0, r1 = int(np.floor(cy - hy)), int(np.ceil(cy + hy)) + 1
    r0, c0 = max(0, r0), max(0, c0)
    return r0, max(r0, min(h, r1)), c0, max(c0, min(w, c1))


def analyze(frame: np.ndarray, dark: np.ndarray | None = None, mask: np.ndarray | None = None, opt: Options | None = None) -> Metrics:
    opt = opt or Options()
    h, w = frame.shape
    saturated = saturated_share(frame, opt.full_scale, mask if opt.hot_pixel_mask else None)
    if opt.analysis == "naive":
        # what a person or a quick lab script does: find the bright blob (a 3 x 3 smoothed image ignores a lone
        # hot pixel), keep the raw pixels above a share of its peak, take their centroid. No dark frame, no
        # baseline, no integration area: the background under the beam and a clipped peak go unnoticed.
        raw = frame.astype(np.float64)
        pad = np.pad(raw, 1, mode="edge")
        smooth = sum(pad[dr : dr + h, dc : dc + w] for dr in (0, 1, 2) for dc in (0, 1, 2)) / 9.0
        img = np.where(smooth >= opt.naive_threshold * smooth.max(), raw, 0.0)
        total, cx, cy, vx, vy = _moments(img, 0, h, 0, w)
        peak = float(smooth.max())
        iterations, converged = 1, True
        r0, r1, c0, c1 = 0, h, 0, w
    else:
        img = corrected(frame, dark, mask, opt)
        r0, r1, c0, c1 = 0, h, 0, w
        total, cx, cy, vx, vy = _moments(img, r0, r1, c0, c1)
        iterations, converged = 1, not opt.iso_aperture
        if opt.iso_aperture and total > 0:
            for iterations in range(2, opt.max_iterations + 2):  # noqa: B007 - read after the loop
                r0, r1, c0, c1 = _window(cx, cy, vx, vy, opt.aperture_factor, h, w)
                t2, cx2, cy2, vx2, vy2 = _moments(img, r0, r1, c0, c1)
                if t2 <= 0:
                    break
                sx, sy = np.sqrt(max(vx, 0.0)), np.sqrt(max(vy, 0.0))
                sx2, sy2 = np.sqrt(max(vx2, 0.0)), np.sqrt(max(vy2, 0.0))
                change = max(abs(sx2 - sx), abs(sy2 - sy)) / max(sx, sy, 1e-9)
                total, cx, cy, vx, vy = t2, cx2, cy2, vx2, vy2
                if change < opt.tolerance:
                    converged = True
                    break
        peak = _box_peak(img, r0, r1, c0, c1) if total > 0 else 0.0
    d4x = 4.0 * float(np.sqrt(max(vx, 0.0))) if total > 0 else float("nan")
    d4y = 4.0 * float(np.sqrt(max(vy, 0.0))) if total > 0 else float("nan")
    edge = bool(
        total > 0
        and (
            cx - d4x / 2 < opt.edge_margin_px
            or cy - d4y / 2 < opt.edge_margin_px
            or cx + d4x / 2 > w - 1 - opt.edge_margin_px
            or cy + d4y / 2 > h - 1 - opt.edge_margin_px
        )
    )
    return Metrics(
        cx=cx,
        cy=cy,
        d4x=d4x,
        d4y=d4y,
        total=total,
        peak=peak,
        peak_fraction=peak / total if total > 0 else float("nan"),
        raw_peak=float(frame.max()),
        saturated=saturated,
        edge=edge,
        iterations=iterations,
        converged=converged,
    )
