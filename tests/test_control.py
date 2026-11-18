"""Interlocks and the shot cycle."""

from __future__ import annotations

import pytest

from lbp.control.interlocks import ShotInputs, evaluate, predicted_fluence


def inputs(**kw) -> ShotInputs:
    base = dict(energy_target_j=10.0, pump=0.8, diode_temp_c=25.0, profile_peak_fraction=0.00038)
    base.update(kw)
    return ShotInputs(**base)


def test_a_normal_shot_is_permitted(cfg):
    d = evaluate(inputs(), cfg, fluence_interlock=True)
    assert d.permit and d.reasons == []
    assert d.predicted_fluence_j_cm2 == pytest.approx(predicted_fluence(10.0, 0.00038, cfg["fluence"]["nf_mm_per_px_at_optic"]))


def test_a_hot_spot_holds_the_shot_and_asks_for_inspection(cfg):
    d = evaluate(inputs(profile_peak_fraction=0.00075), cfg, fluence_interlock=True)
    assert not d.permit and d.action == "inspect"
    assert "predicted peak fluence" in d.reasons[0]


def test_without_a_profile_the_shot_is_held(cfg):
    assert not evaluate(inputs(profile_peak_fraction=None), cfg, True).permit
    assert not evaluate(inputs(profile_saturated=True), cfg, True).permit


def test_status_quo_checks_only_the_energy_limit(cfg):
    assert evaluate(inputs(profile_peak_fraction=0.00075), cfg, fluence_interlock=False).permit
    assert not evaluate(inputs(pump=5.0), cfg, fluence_interlock=False).permit


@pytest.mark.parametrize(
    "kw, word",
    [
        ({"device_faults": ("nfc",)}, "nfc"),
        ({"alignment_fault": "actuator not moving the beam: M1x"}, "M1x"),
        ({"diode_temp_c": 30.0}, "diode"),
        ({"beam_lost": True}, "diagnostic cameras"),
        ({"alignment_error": 1.4}, "tolerance"),
    ],
)
def test_each_rule_says_why(cfg, kw, word):
    d = evaluate(inputs(**kw), cfg, True)
    assert not d.permit and any(word in r for r in d.reasons)


def test_untraceable_energy_is_a_warning_not_a_hold(cfg):
    d = evaluate(inputs(energy_cal_valid=False), cfg, True)
    assert d.permit and d.warnings


def test_every_fired_shot_had_a_permit_and_carries_its_calibrations(platform_day):
    ops = platform_day.ops
    decisions = {did: d for (did, _, _, _, d) in ops.decisions}
    assert ops.shots
    for s in ops.shots:
        assert decisions[s.decision_id].permit
        assert s.calibrations["matrix"].startswith("matrix-")
        assert s.calibrations["nf_camera"] and s.calibrations["energy"]
        assert s.calibrations["approved_by"]  # above the two-person energy


def test_a_day_of_the_platform_stays_in_spec(platform_day, cfg):
    from evals.truth import score

    s = score(platform_day)
    assert s["damage_events"] == 0
    assert s["in_spec_share"] > 0.9
    assert s["shots_per_day"] > 100


def test_hot_spot_is_held_and_inspected(ops_factory):
    line, ops = ops_factory()
    ops.start_of_day(0)
    line.hotspot_active, line.hotspot_at = True, (2.0, 1.0)
    rec = ops.cycle()
    assert rec is None
    assert ops.decisions[-1][4].action == "inspect"
    assert not line.hotspot_active  # the inspection cleaned it
    assert not any(p.damaged for p in line.pulses)


def test_status_quo_fires_into_the_hot_spot(ops_factory):
    line, ops = ops_factory("manual_ops")
    ops.start_of_day(0)
    line.hotspot_active, line.hotspot_at = True, (2.0, 1.0)
    rec = ops.cycle()
    assert rec is not None
    assert any(p.damaged for p in line.pulses)
