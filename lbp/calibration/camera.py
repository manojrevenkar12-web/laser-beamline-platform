"""Camera calibration: the dark frame, the hot-pixel map and the exposure for the next frame."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import median_filter

from lbp.devices.drivers import Camera

_ids = itertools.count(1)


@dataclass
class CameraCal:
    camera: str
    day: int
    exposure: float
    dark: np.ndarray
    mask: np.ndarray
    cal_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.cal_id:
            self.cal_id = f"{self.camera}-dark-{next(_ids):04d}"

    @property
    def hot_pixels(self) -> int:
        return int(self.mask.sum())

    def summary(self) -> dict:
        return {"cal_id": self.cal_id, "camera": self.camera, "day": self.day, "exposure": self.exposure, "hot_pixels": self.hot_pixels}


def measure_dark(cam: Camera, exposure: float, day: int, cfg: dict) -> CameraCal:
    """Average dark frames; a pixel is hot when it stands above the local background by `hot_pixel_sigma`
    robust standard deviations (median absolute deviation of the residual)."""
    frames = [cam.dark(exposure).image.astype(np.float64) for _ in range(int(cfg["dark_frames"]))]
    dark = np.mean(frames, axis=0)
    smooth = median_filter(dark, size=int(cfg["hot_pixel_window"]), mode="nearest")
    resid = dark - smooth
    mad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826
    mask = resid > float(cfg["hot_pixel_sigma"]) * max(mad, 1e-6)
    return CameraCal(cam.name, day, exposure, dark, mask)


def next_exposure(exposure: float, peak: float, dark_level: float, saturated: float, cfg: dict) -> float:
    """Exposure for the next frame of the same kind: halve on saturation, otherwise steer the beam peak to the
    target share of the usable range when it leaves the [min, max] band."""
    usable = float(cfg["full_scale"]) - dark_level
    lo, hi = float(cfg["exposure_min"]), float(cfg["exposure_max"])
    if saturated > 0:
        return max(lo, exposure * 0.5)
    if peak <= 0 or not np.isfinite(peak):
        return exposure
    frac = peak / usable
    if frac > float(cfg["max_peak_fraction"]) or frac < float(cfg["min_peak_fraction"]):
        return float(min(hi, max(lo, exposure * float(cfg["target_peak_fraction"]) / frac)))
    return exposure
