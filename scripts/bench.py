"""Benchmark the beam analysis engines on camera-sized frames and write reports/bench.json.

python3 scripts/bench.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lbp.diagnostics import beam, native  # noqa: E402


def frame(n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(xx - n * 0.48, yy - n * 0.52)
    sig = 2400 * np.exp(-2 * (r / (n * 0.23)) ** 12)
    dark = 100 + 50 * (xx - n / 2) / n
    img = np.clip(np.rint(dark + sig + rng.normal(0, 4, (n, n))), 0, 4095).astype(np.uint16)
    mask = np.zeros((n, n), dtype=bool)
    for _ in range(n // 8):
        rr, cc = rng.integers(0, n, 2)
        img[rr, cc] = 4000
        mask[rr, cc] = True
    return img, dark, mask


def timeit(fn, *args, repeat: int) -> float:
    fn(*args)
    t0 = time.perf_counter()
    for _ in range(repeat):
        fn(*args)
    return (time.perf_counter() - t0) / repeat


def main() -> None:
    rng = np.random.default_rng(1)
    rows = []
    for n, repeat in ((128, 200), (512, 20), (1024, 5), (2048, 2)):
        img, dark, mask = frame(n, rng)
        opt = beam.Options()
        py = timeit(beam.analyze, img, dark, mask, opt, repeat=repeat)
        cpp = timeit(native.analyze, img, dark, mask, opt, repeat=repeat) if native.available else float("nan")
        rows.append({"pixels": f"{n} x {n}", "numpy_ms": round(py * 1e3, 3), "cpp_ms": round(cpp * 1e3, 3), "speedup": round(py / cpp, 1)})
        print(rows[-1])
    out = {"engine": native.ENGINE, "frames": rows}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "bench.json").write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
