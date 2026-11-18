"""The C++ beam analysis (cpp/beamcore) behind the same interface as the NumPy reference.

The naive status-quo analysis exists only in Python. If the extension is not built, `available` is False and
`analyze` falls back to the reference; the platform logs which engine it runs (`ENGINE`).
"""

from __future__ import annotations

import numpy as np

from lbp.diagnostics import beam

try:
    from lbp import _beamcore  # type: ignore[attr-defined]

    available = True
except ImportError:  # pragma: no cover - CI builds the extension
    _beamcore = None
    available = False

ENGINE = "beamcore (C++)" if available else "numpy reference"


def _options(opt: beam.Options) -> dict:
    return {
        "background": opt.background,
        "hot_pixel_mask": opt.hot_pixel_mask,
        "iso_aperture": opt.iso_aperture,
        "aperture_factor": opt.aperture_factor,
        "max_iterations": opt.max_iterations,
        "tolerance": opt.tolerance,
        "ring_px": opt.ring_px,
        "full_scale": opt.full_scale,
        "edge_margin_px": opt.edge_margin_px,
    }


def analyze(
    frame: np.ndarray, dark: np.ndarray | None = None, mask: np.ndarray | None = None, opt: beam.Options | None = None
) -> beam.Metrics:
    opt = opt or beam.Options()
    if opt.analysis != "iso" or not available:
        return beam.analyze(frame, dark, mask, opt)
    d = np.ascontiguousarray(dark, dtype=np.float64) if dark is not None else None
    m = np.ascontiguousarray(mask, dtype=np.uint8) if mask is not None else None
    out = _beamcore.analyze(np.ascontiguousarray(frame, dtype=np.uint16), d, m, _options(opt))
    return beam.Metrics(**out)
