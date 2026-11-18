// beamcore: ISO 11146 beam analysis of 12-bit camera frames.
//
// The same algorithm as lbp/diagnostics/beam.py (the reference), in one pass-friendly C++ implementation for
// the camera rate. tests/test_beamcore.py checks that both agree on random frames to 1e-9 relative.
#pragma once

#include <cstdint>
#include <span>

namespace beamcore {

struct Options {
    bool background = true;      // subtract the dark frame and the border baseline
    bool hot_pixel_mask = true;  // replace masked pixels by the median of their unmasked neighbours
    bool iso_aperture = true;    // iterate the integration area (ISO 11146-2)
    double aperture_factor = 3.0;
    int max_iterations = 10;
    double tolerance = 0.01;
    int ring_px = 4;
    int full_scale = 4095;
    int edge_margin_px = 2;
};

struct Metrics {
    double cx = 0, cy = 0, d4x = 0, d4y = 0;
    double total = 0, peak = 0, peak_fraction = 0, raw_peak = 0, saturated = 0;
    bool edge = false;
    int iterations = 0;
    bool converged = false;
};

// frame: h*w row-major counts. dark: h*w or empty. mask: h*w (nonzero = hot pixel) or empty.
Metrics analyze(std::span<const std::uint16_t> frame, int h, int w, std::span<const double> dark,
                std::span<const std::uint8_t> mask, const Options& opt);

double saturated_share(std::span<const std::uint16_t> frame, int h, int w, int full_scale,
                       std::span<const std::uint8_t> mask = {});

}  // namespace beamcore
