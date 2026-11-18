# 2. ISO 11146 analysis in C++, with a NumPy reference

## Context

Every pulse produces two camera frames, and alignment needs several pulses per iteration. The beam analysis
must be fast enough for the camera rate on full-size sensors, and correct in the ways ISO 11146 requires: dark
and baseline subtraction, an integration area of three beam widths, hot pixels handled.

## Decision

`lbp/diagnostics/beam.py` is the reference: plain NumPy, easy to read and to review against the standard.
`cpp/beamcore` implements the same algorithm in C++20 and is called through pybind11. A property test runs
both on random frames (spot shape, background gradient, hot pixels, options) and requires agreement to 1e-9.
The platform uses the C++ engine when it is built and says which engine ran.

## Consequences

Any change to the algorithm is made twice and the property test keeps the two honest. The speed-up is measured
in `scripts/bench.py` and grows with the frame size. The naive status-quo analysis exists only in Python,
because it is only there to be compared against.
