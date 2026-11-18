// Python bindings: lbp._beamcore.analyze(frame, dark, mask, options) -> dict
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <optional>

#include "beamcore.hpp"

namespace py = pybind11;

namespace {

using U16 = py::array_t<std::uint16_t, py::array::c_style | py::array::forcecast>;
using F64 = py::array_t<double, py::array::c_style | py::array::forcecast>;
using U8 = py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast>;

py::dict analyze(const U16& frame, const std::optional<F64>& dark, const std::optional<U8>& mask, const py::dict& o) {
    if (frame.ndim() != 2) throw std::invalid_argument("frame must be 2-D");
    const int h = static_cast<int>(frame.shape(0)), w = static_cast<int>(frame.shape(1));
    const std::size_t n = static_cast<std::size_t>(h) * w;
    beamcore::Options opt;
    opt.background = o["background"].cast<bool>();
    opt.hot_pixel_mask = o["hot_pixel_mask"].cast<bool>();
    opt.iso_aperture = o["iso_aperture"].cast<bool>();
    opt.aperture_factor = o["aperture_factor"].cast<double>();
    opt.max_iterations = o["max_iterations"].cast<int>();
    opt.tolerance = o["tolerance"].cast<double>();
    opt.ring_px = o["ring_px"].cast<int>();
    opt.full_scale = o["full_scale"].cast<int>();
    opt.edge_margin_px = o["edge_margin_px"].cast<int>();

    std::span<const double> dspan;
    if (dark) {
        if (static_cast<std::size_t>(dark->size()) != n) throw std::invalid_argument("dark shape");
        dspan = {dark->data(), n};
    }
    std::span<const std::uint8_t> mspan;
    if (mask) {
        if (static_cast<std::size_t>(mask->size()) != n) throw std::invalid_argument("mask shape");
        mspan = {mask->data(), n};
    }
    beamcore::Metrics m;
    {
        py::gil_scoped_release release;
        m = beamcore::analyze({frame.data(), n}, h, w, dspan, mspan, opt);
    }
    py::dict out;
    out["cx"] = m.cx;
    out["cy"] = m.cy;
    out["d4x"] = m.d4x;
    out["d4y"] = m.d4y;
    out["total"] = m.total;
    out["peak"] = m.peak;
    out["peak_fraction"] = m.peak_fraction;
    out["raw_peak"] = m.raw_peak;
    out["saturated"] = m.saturated;
    out["edge"] = m.edge;
    out["iterations"] = m.iterations;
    out["converged"] = m.converged;
    return out;
}

}  // namespace

PYBIND11_MODULE(_beamcore, mod) {
    mod.doc() = "ISO 11146 beam analysis (C++)";
    mod.def("analyze", &analyze, py::arg("frame"), py::arg("dark") = py::none(), py::arg("mask") = py::none(),
            py::arg("options"));
}
