"""A short campaign of the platform and the status quo on the dev beamline, for the charts and the console.

The hot spot on dev beamline 11 appears on shift 3, so four shifts show alignment, calibration, an interlock
hold and the status quo firing into the hot spot.
"""

from __future__ import annotations

import functools
import tempfile

from evals.operate import Run, operate

SEED, DAYS, SHIFT = 11, 4, 3


@functools.lru_cache(maxsize=4)
def run(design: str, frames: bool = False) -> Run:
    root = tempfile.mkdtemp(prefix=f"lbp-{design}-") if frames else None
    return operate(design, SEED, days=DAYS, store_root=root, frames=frames)
