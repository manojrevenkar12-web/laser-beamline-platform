"""ISO 11146 diagnostics: the reference implementation, and the C++ engine agreeing with it."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from lbp.diagnostics import beam, native


def spot(n=128, x0=60.3, y0=70.8, w=6.0, amp=2000.0, offset=100.0, gradient=0.0, flat=False):
    yy, xx = np.mgrid[0:n, 0:n]
    r2 = (xx - x0) ** 2 + (yy - y0) ** 2
    sig = amp * (np.exp(-2.0 * (np.sqrt(r2) / w) ** 12) if flat else np.exp(-2.0 * r2 / w**2))
    bg = offset + gradient * (xx - n / 2) / n
    return np.clip(np.rint(bg + sig), 0, 4095).astype(np.uint16), bg


def test_gaussian_centroid_and_d4sigma():
    f, bg = spot()
    m = beam.analyze(f, bg, None, beam.Options())
    assert abs(m.cx - 60.3) < 0.02 and abs(m.cy - 70.8) < 0.02
    assert abs(m.d4x - 12.0) < 0.1  # D4sigma of a Gaussian is twice its 1/e^2 radius
    assert m.converged


def test_uncorrected_background_biases_the_centroid():
    f, bg = spot(x0=30.0, y0=30.0, gradient=80.0)
    good = beam.analyze(f, bg, None, beam.Options())
    raw = beam.analyze(f, None, None, beam.Options(background=False, iso_aperture=False))
    assert abs(good.cx - 30.0) < 0.05
    assert raw.cx - 30.0 > 1.0


def test_hot_pixel_is_replaced_when_masked():
    f, bg = spot(x0=64.0, y0=64.0, amp=1500.0)
    f[66, 70] = 4095
    mask = np.zeros(f.shape, dtype=bool)
    mask[66, 70] = True
    assert abs(beam.analyze(f, bg, mask, beam.Options()).cx - 64.0) < 0.02
    assert abs(beam.analyze(f, bg, None, beam.Options()).cx - 64.0) > 0.05


def test_naive_blob_ignores_a_lone_hot_pixel_but_its_fluence_follows_the_background():
    f, _ = spot(x0=64.0, y0=64.0, w=10.0, amp=1200.0, offset=0.0)
    f[20, 110] = 4095
    naive = beam.analyze(f, None, None, beam.Options(analysis="naive"))
    assert abs(naive.cx - 64.0) < 0.1  # the smoothed blob is not fooled by one pixel
    lit, bg = spot(x0=64.0, y0=64.0, w=10.0, amp=1200.0, offset=400.0)
    dark, _ = spot(x0=64.0, y0=64.0, w=10.0, amp=1200.0, offset=0.0)
    naive_lit = beam.analyze(lit, None, None, beam.Options(analysis="naive"))
    naive_dark = beam.analyze(dark, None, None, beam.Options(analysis="naive"))
    iso_lit = beam.analyze(lit, bg, None, beam.Options())
    iso_dark = beam.analyze(dark, np.zeros_like(bg), None, beam.Options())
    # the same beam on a brighter background: the naive peak share (its fluence estimate) moves, ISO's does not
    assert abs(naive_lit.peak_fraction / naive_dark.peak_fraction - 1.0) > 0.05
    assert iso_lit.peak_fraction == pytest.approx(iso_dark.peak_fraction, rel=0.01)


def test_saturation_counts_a_clipped_beam_not_an_isolated_hot_pixel():
    clipped, _ = spot(amp=6000.0, w=8.0)
    assert beam.saturated_share(clipped, 4095) > 0.001
    quiet, _ = spot(amp=1000.0)
    quiet[5, 5] = 4095
    assert beam.saturated_share(quiet, 4095) == 0.0


def test_empty_frame_reports_no_beam():
    f = np.full((64, 64), 100, dtype=np.uint16)
    m = beam.analyze(f, np.full((64, 64), 100.0), None, beam.Options())
    assert m.total == 0 and math.isnan(m.d4x)


@pytest.mark.skipif(not native.available, reason="beamcore extension not built")
@settings(max_examples=60, deadline=None)
@given(
    x0=st.floats(20, 108),
    y0=st.floats(20, 108),
    w=st.floats(3, 30),
    amp=st.floats(200, 5000),
    gradient=st.floats(-80, 80),
    flat=st.booleans(),
    background=st.booleans(),
    mask_on=st.booleans(),
    iso=st.booleans(),
    hot=st.integers(0, 12),
    seed=st.integers(0, 10_000),
)
def test_cpp_engine_matches_the_reference(x0, y0, w, amp, gradient, flat, background, mask_on, iso, hot, seed):
    rng = np.random.default_rng(seed)
    f, bg = spot(x0=x0, y0=y0, w=w, amp=amp, gradient=gradient, flat=flat)
    f = np.clip(f.astype(float) + rng.normal(0, 4, f.shape), 0, 4095).astype(np.uint16)
    mask = np.zeros(f.shape, dtype=bool)
    for _ in range(hot):
        r, c = rng.integers(0, 128, 2)
        f[r, c] = rng.integers(1000, 4096)
        mask[r, c] = True
    opt = beam.Options(background=background, hot_pixel_mask=mask_on, iso_aperture=iso)
    ref = beam.analyze(f, bg, mask, opt)
    cpp = native.analyze(f, bg, mask, opt)
    for key in ("cx", "cy", "d4x", "d4y", "total", "peak", "peak_fraction", "saturated", "raw_peak"):
        a, b = getattr(ref, key), getattr(cpp, key)
        if isinstance(a, float) and math.isnan(a):
            assert math.isnan(b), key
        else:
            assert b == pytest.approx(a, rel=1e-9, abs=1e-9), key
    assert (ref.iterations, ref.converged, ref.edge) == (cpp.iterations, cpp.converged, cpp.edge)


@pytest.mark.skipif(not native.available, reason="beamcore extension not built")
def test_cpp_engine_is_faster_on_camera_frames():
    import time

    f, bg = spot(n=512, x0=250.0, y0=260.0, w=60.0, flat=True)
    mask = np.zeros(f.shape, dtype=bool)
    opt = beam.Options()
    t0 = time.perf_counter()
    for _ in range(5):
        beam.analyze(f, bg, mask, opt)
    py = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(5):
        native.analyze(f, bg, mask, opt)
    cpp = time.perf_counter() - t0
    assert cpp < py
