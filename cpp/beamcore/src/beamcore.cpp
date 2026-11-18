#include "beamcore.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

namespace beamcore {
namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

struct Moments {
    double total = 0, cx = kNaN, cy = kNaN, vx = kNaN, vy = kNaN;
};

Moments moments(const std::vector<double>& img, int w, int r0, int r1, int c0, int c1) {
    if (r1 <= r0 || c1 <= c0) return Moments{};
    double total = 0, sx = 0, sy = 0;
    for (int r = r0; r < r1; ++r) {
        const double* row = img.data() + static_cast<std::size_t>(r) * w;
        for (int c = c0; c < c1; ++c) {
            total += row[c];
            sx += row[c] * c;
            sy += row[c] * r;
        }
    }
    Moments m;
    if (total <= 0) {
        m.total = 0;
        return m;
    }
    m.total = total;
    m.cx = sx / total;
    m.cy = sy / total;
    double vx = 0, vy = 0;
    for (int r = r0; r < r1; ++r) {
        const double* row = img.data() + static_cast<std::size_t>(r) * w;
        const double dy = r - m.cy;
        for (int c = c0; c < c1; ++c) {
            const double dx = c - m.cx;
            vx += row[c] * dx * dx;
            vy += row[c] * dy * dy;
        }
    }
    m.vx = vx / total;
    m.vy = vy / total;
    return m;
}

double median(std::vector<double>& v) {
    std::sort(v.begin(), v.end());
    const std::size_t n = v.size();
    return n % 2 ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

double box_peak(const std::vector<double>& img, int h, int w, int r0, int r1, int c0, int c1) {
    if (r1 <= r0 || c1 <= c0) return 0.0;
    double best = -std::numeric_limits<double>::infinity();
    for (int r = r0; r < r1; ++r) {
        for (int c = c0; c < c1; ++c) {
            double acc = 0;
            for (int dr = -1; dr <= 1; ++dr) {
                const int rr = std::clamp(r + dr, 0, h - 1);  // edge padding, as numpy.pad(mode="edge")
                for (int dc = -1; dc <= 1; ++dc) {
                    const int cc = std::clamp(c + dc, 0, w - 1);
                    acc += img[static_cast<std::size_t>(rr) * w + cc];
                }
            }
            best = std::max(best, acc / 9.0);
        }
    }
    return best;
}

}  // namespace

double saturated_share(std::span<const std::uint16_t> frame, int h, int w, int full_scale,
                       std::span<const std::uint8_t> mask) {
    std::size_t count = 0;
    for (int r = 0; r < h; ++r) {
        for (int c = 0; c < w; ++c) {
            const std::size_t i = static_cast<std::size_t>(r) * w + c;
            if (frame[i] < full_scale) continue;
            if (!mask.empty() && mask[i]) continue;
            int bright = 0;
            for (int dr = -1; dr <= 1; ++dr) {
                for (int dc = -1; dc <= 1; ++dc) {
                    if (dr == 0 && dc == 0) continue;
                    const int rr = r + dr, cc = c + dc;
                    if (rr < 0 || rr >= h || cc < 0 || cc >= w) continue;
                    if (frame[static_cast<std::size_t>(rr) * w + cc] >= full_scale / 2.0) ++bright;
                }
            }
            if (bright >= 2) ++count;
        }
    }
    return static_cast<double>(count) / (static_cast<double>(h) * w);
}

Metrics analyze(std::span<const std::uint16_t> frame, int h, int w, std::span<const double> dark,
                std::span<const std::uint8_t> mask, const Options& opt) {
    const std::size_t n = static_cast<std::size_t>(h) * w;
    Metrics out;
    out.saturated = saturated_share(frame, h, w, opt.full_scale, opt.hot_pixel_mask ? mask : std::span<const std::uint8_t>{});
    std::vector<double> img(n);
    double raw_peak = 0;
    for (std::size_t i = 0; i < n; ++i) {
        img[i] = frame[i];
        raw_peak = std::max(raw_peak, img[i]);
        if (opt.background && !dark.empty()) img[i] -= dark[i];
    }
    out.raw_peak = raw_peak;

    if (opt.hot_pixel_mask && !mask.empty()) {
        const std::vector<double> src = img;
        std::vector<double> vals;
        vals.reserve(8);
        for (int r = 0; r < h; ++r) {
            for (int c = 0; c < w; ++c) {
                if (!mask[static_cast<std::size_t>(r) * w + c]) continue;
                vals.clear();
                for (int dr = -1; dr <= 1; ++dr) {
                    for (int dc = -1; dc <= 1; ++dc) {
                        if (dr == 0 && dc == 0) continue;
                        const int rr = r + dr, cc = c + dc;
                        if (rr < 0 || rr >= h || cc < 0 || cc >= w) continue;
                        const std::size_t j = static_cast<std::size_t>(rr) * w + cc;
                        if (!mask[j]) vals.push_back(src[j]);
                    }
                }
                img[static_cast<std::size_t>(r) * w + c] = vals.empty() ? 0.0 : median(vals);
            }
        }
    }

    if (opt.background && opt.ring_px > 0) {
        double sum = 0;
        std::size_t count = 0;
        const int k = opt.ring_px;
        for (int r = 0; r < h; ++r) {
            for (int c = 0; c < w; ++c) {
                if (r < k || r >= h - k || c < k || c >= w - k) {
                    sum += img[static_cast<std::size_t>(r) * w + c];
                    ++count;
                }
            }
        }
        const double base = count ? sum / static_cast<double>(count) : 0.0;
        for (auto& v : img) v -= base;
    }

    int r0 = 0, r1 = h, c0 = 0, c1 = w;
    Moments m = moments(img, w, r0, r1, c0, c1);
    int iterations = 1;
    bool converged = !opt.iso_aperture;
    if (opt.iso_aperture && m.total > 0) {
        for (iterations = 2; iterations < opt.max_iterations + 2; ++iterations) {
            const double hx = opt.aperture_factor * 2.0 * std::sqrt(std::max(m.vx, 0.0));
            const double hy = opt.aperture_factor * 2.0 * std::sqrt(std::max(m.vy, 0.0));
            c0 = std::max(0, static_cast<int>(std::floor(m.cx - hx)));
            c1 = std::max(c0, std::min(w, static_cast<int>(std::ceil(m.cx + hx)) + 1));
            r0 = std::max(0, static_cast<int>(std::floor(m.cy - hy)));
            r1 = std::max(r0, std::min(h, static_cast<int>(std::ceil(m.cy + hy)) + 1));
            const Moments m2 = moments(img, w, r0, r1, c0, c1);
            if (m2.total <= 0) break;
            const double sx = std::sqrt(std::max(m.vx, 0.0)), sy = std::sqrt(std::max(m.vy, 0.0));
            const double sx2 = std::sqrt(std::max(m2.vx, 0.0)), sy2 = std::sqrt(std::max(m2.vy, 0.0));
            const double change = std::max(std::abs(sx2 - sx), std::abs(sy2 - sy)) / std::max({sx, sy, 1e-9});
            m = m2;
            if (change < opt.tolerance) {
                converged = true;
                break;
            }
        }
        if (iterations == opt.max_iterations + 2) iterations = opt.max_iterations + 1;
    }

    out.iterations = iterations;
    out.converged = converged;
    out.total = m.total;
    out.cx = m.cx;
    out.cy = m.cy;
    if (m.total > 0) {
        out.peak = box_peak(img, h, w, r0, r1, c0, c1);
        out.d4x = 4.0 * std::sqrt(std::max(m.vx, 0.0));
        out.d4y = 4.0 * std::sqrt(std::max(m.vy, 0.0));
        out.peak_fraction = out.peak / m.total;
        const double mg = opt.edge_margin_px;
        out.edge = (m.cx - out.d4x / 2 < mg) || (m.cy - out.d4y / 2 < mg) || (m.cx + out.d4x / 2 > w - 1 - mg) ||
                   (m.cy + out.d4y / 2 > h - 1 - mg);
    } else {
        out.peak = 0;
        out.d4x = out.d4y = out.peak_fraction = kNaN;
        out.edge = false;
    }
    return out;
}

}  // namespace beamcore
