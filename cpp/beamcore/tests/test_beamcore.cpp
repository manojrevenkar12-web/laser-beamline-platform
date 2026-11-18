// Unit tests for beamcore without a test framework: each check prints and counts failures.
#include <cmath>
#include <cstdio>
#include <vector>

#include "beamcore.hpp"

namespace {

int failures = 0;

void check(bool ok, const char* what) {
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) ++failures;
}

std::vector<std::uint16_t> gaussian(int n, double x0, double y0, double w, double amp, double offset) {
    std::vector<std::uint16_t> f(static_cast<std::size_t>(n) * n);
    for (int r = 0; r < n; ++r)
        for (int c = 0; c < n; ++c) {
            const double v = offset + amp * std::exp(-2.0 * ((c - x0) * (c - x0) + (r - y0) * (r - y0)) / (w * w));
            f[static_cast<std::size_t>(r) * n + c] = static_cast<std::uint16_t>(std::lround(std::min(v, 4095.0)));
        }
    return f;
}

}  // namespace

int main() {
    const int n = 128;
    beamcore::Options opt;

    {  // a Gaussian on a flat background: centroid and D4sigma = 2w
        auto f = gaussian(n, 40.3, 70.8, 6.0, 2000, 100);
        std::vector<double> dark(static_cast<std::size_t>(n) * n, 100.0);
        auto m = beamcore::analyze(f, n, n, dark, {}, opt);
        check(std::abs(m.cx - 40.3) < 0.02 && std::abs(m.cy - 70.8) < 0.02, "centroid of a Gaussian spot");
        check(std::abs(m.d4x - 12.0) < 0.1 && std::abs(m.d4y - 12.0) < 0.1, "D4sigma of a Gaussian is twice its radius");
        check(m.converged, "integration area converges");
    }
    {  // without background subtraction the background drags the centroid toward the frame centre
        auto f = gaussian(n, 30.0, 30.0, 5.0, 2000, 100);
        beamcore::Options raw = opt;
        raw.background = false;
        raw.iso_aperture = false;
        auto m = beamcore::analyze(f, n, n, {}, {}, raw);
        check(m.cx > 31.0, "uncorrected background biases the centroid");
    }
    {  // a hot pixel inside the integration area is replaced, not counted
        auto f = gaussian(n, 64.0, 64.0, 6.0, 1500, 100);
        std::vector<double> dark(static_cast<std::size_t>(n) * n, 100.0);
        std::vector<std::uint8_t> mask(static_cast<std::size_t>(n) * n, 0);
        const std::size_t hot = static_cast<std::size_t>(66) * n + 70;
        f[hot] = 4095;
        mask[hot] = 1;
        auto with = beamcore::analyze(f, n, n, dark, mask, opt);
        auto without = beamcore::analyze(f, n, n, dark, {}, opt);
        check(std::abs(with.cx - 64.0) < 0.02, "masked hot pixel leaves the centroid alone");
        check(std::abs(without.cx - 64.0) > 0.05, "an unmasked hot pixel moves the centroid");
    }
    {  // a clipped beam counts as saturated; an isolated full-scale pixel does not
        auto f = gaussian(n, 64.0, 64.0, 8.0, 6000, 100);
        check(beamcore::saturated_share(f, n, n, 4095) > 0.001, "clipped beam is saturated");
        auto g = gaussian(n, 64.0, 64.0, 8.0, 1000, 100);
        g[5 * n + 5] = 4095;
        check(beamcore::saturated_share(g, n, n, 4095) == 0.0, "isolated hot pixel is not saturation");
    }
    {  // an empty frame has no beam
        std::vector<std::uint16_t> f(static_cast<std::size_t>(n) * n, 100);
        std::vector<double> dark(static_cast<std::size_t>(n) * n, 100.0);
        auto m = beamcore::analyze(f, n, n, dark, {}, opt);
        check(m.total == 0 && std::isnan(m.d4x), "empty frame reports no beam");
    }
    std::printf("%d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
