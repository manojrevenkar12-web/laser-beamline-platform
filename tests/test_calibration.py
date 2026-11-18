"""Alignment, camera and energy calibration on the simulated beamline."""

from __future__ import annotations

import math

import numpy as np
import pytest

from lbp.calibration import energy
from lbp.calibration.alignment import nominal_matrix
from lbp.calibration.camera import next_exposure


def test_dark_frame_finds_the_hot_pixels(ops_factory):
    line, ops = ops_factory()
    ops.calibrate_cameras()
    cal = ops.cam_cal["nf"]
    truth = set(line.nf_cam.hot)
    found = {tuple(rc) for rc in np.argwhere(cal.mask)}
    assert len(truth & found) >= 0.9 * len(truth)
    assert len(found - truth) <= 2


def test_measured_matrix_is_close_to_the_truth(ops_factory):
    line, ops = ops_factory()
    ops.calibrate_cameras()
    cal = ops.aligner.calibrate(0)
    assert cal.source == "measured" and not ops.aligner.fault
    truth = line.matrix * line.step[None, :]
    # pointing rows: from single-axis pokes, within a few per cent
    ff_err = np.linalg.norm(cal.matrix[2:] - truth[2:]) / np.linalg.norm(truth[2:])
    assert ff_err < 0.06
    # near-field rows along the centring walks (pointing held), where they matter, within 15 %
    _, _, vt = np.linalg.svd(truth[2:])
    walk = vt[2:].T
    nf_err = np.linalg.norm((cal.matrix[:2] - truth[:2]) @ walk) / np.linalg.norm(truth[:2] @ walk)
    assert nf_err < 0.15
    # backlash and the reverse ratio of every axis
    assert np.all(np.abs(cal.backlash - line.backlash) < 10)
    assert np.all(np.abs(cal.reverse_ratio - line.reverse) < 0.1)


def test_alignment_brings_the_beam_inside_tolerance(ops_factory, cfg):
    line, ops = ops_factory()
    ops.start_of_day(0)
    pos = line.beam_position()
    assert abs(pos[0]) < cfg["tolerance"]["nf_mm"] and abs(pos[1]) < cfg["tolerance"]["nf_mm"]
    assert np.hypot(pos[2], pos[3]) < cfg["tolerance"]["ff_urad"]


def test_a_stuck_actuator_is_reported_and_holds_the_shots(ops_factory):
    line, ops = ops_factory()
    line.step[2] = 0.0  # M2x no longer moves the mirror
    ops.calibrate_cameras()
    ops.aligner.calibrate(0)
    assert "M2x" in ops.aligner.fault
    rec = ops.cycle()
    assert rec is None
    assert any("M2x" in r for r in ops.decisions[-1][4].reasons)


def test_travel_limit_stops_alignment(ops_factory, cfg):
    line, ops = ops_factory()
    ops.aligner.travel[0] = int(cfg["alignment"]["travel_limit_steps"]) - 10
    ops.aligner.move(0, 50)
    assert "travel limit" in ops.aligner.fault


def test_nominal_matrix_has_the_drawing_geometry(cfg):
    m = nominal_matrix(cfg)
    assert m[2, 0] == pytest.approx(2 * cfg["alignment"]["nominal_step_urad"])
    assert m[0, 0] == pytest.approx(2 * cfg["alignment"]["nominal_lever_m"][0] * 1e-3 * cfg["alignment"]["nominal_step_urad"])


def test_exposure_halves_on_saturation_and_steers_to_target(cfg):
    cam = cfg["camera"]
    assert next_exposure(1.0, 4000, 100, 0.01, cam) == pytest.approx(0.5)
    steered = next_exposure(1.0, 0.95 * (cam["full_scale"] - 100), 100, 0.0, cam)
    assert steered == pytest.approx(cam["target_peak_fraction"] / 0.95, rel=1e-6)
    assert next_exposure(1.0, 0.6 * (cam["full_scale"] - 100), 100, 0.0, cam) == 1.0


def test_energy_cross_calibration_uncertainty_and_refusals():
    raw = [10.0 * (1 + 0.004 * math.sin(i)) for i in range(10)]
    ref = [r * 1.02 for r in raw]
    cal = energy.evaluate(3, raw, ref, 0.008, 1.0, 0.015)
    assert cal.applied and cal.factor == pytest.approx(1.02, rel=1e-9)
    assert cal.u_k2 >= 0.008  # never better than the reference certificate
    few = energy.evaluate(3, raw[:3], ref[:3], 0.008, 1.0, 0.015)
    assert not few.applied and few.factor == 1.0
    loose = energy.evaluate(3, raw, ref, 0.04, 1.0, 0.015)
    assert not loose.applied


def test_overdue_reference_is_refused(ops_factory, wcfg):
    world = {**wcfg, "reference_meter": {**wcfg["reference_meter"], "certificate_due_day": -1}}
    line, ops = ops_factory(world=world)
    ops.calibrate_cameras()
    ops.cross_calibrate_energy()
    assert ops.energy_cals == []
    assert any(a.kind == "reference-overdue" for a in ops.alerts)
    assert not line.reference_inserted


def test_cross_calibration_corrects_a_drifted_meter(ops_factory, wcfg):
    world = {**wcfg, "energy_meter": {**wcfg["energy_meter"], "vendor_factor": 0.95}}
    line, ops = ops_factory(world=world)
    ops.calibrate_cameras()
    ops.start_of_day(0)
    cal = ops.energy_cals[-1]
    assert cal.applied
    assert cal.factor == pytest.approx(1 / 0.95 * (1 + line.reference_bias), rel=0.01)
