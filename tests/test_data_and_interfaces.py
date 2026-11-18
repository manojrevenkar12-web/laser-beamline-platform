"""The data store, DDS, webhooks, the HTTP API and the logbook handover."""

from __future__ import annotations

import json
import time

import numpy as np
import pytest

from lbp.api.webhooks import Dispatcher, sign, verify
from lbp.bus.dds import HAVE_DDS, MemoryBus, ShotMsg
from lbp.data.store import Conflict, Store
from lbp.elog import handover


def shot(**kw) -> dict:
    rec = {
        "shot_id": "S000-00001",
        "pulse_id": 7,
        "day": 0,
        "t_s": 12.5,
        "purpose": "experiment",
        "pump": 0.8,
        "energy_target_j": 10.0,
        "energy_raw_j": 9.9,
        "energy_reported_j": 10.0,
        "nf_x_mm": 0.1,
        "nf_y_mm": -0.1,
        "ff_x_urad": 1.0,
        "ff_y_urad": -2.0,
        "nf_d4_mm": 30.0,
        "peak_fraction": 0.0004,
        "fluence_est_j_cm2": 1.6,
        "predicted_fluence_j_cm2": 1.6,
        "saturated": 0,
        "pre_error": [0.0, 0.0, 0.5, 0.5],
        "calibrations": {"matrix": "matrix-0001"},
        "decision_id": "d-000001",
    }
    rec.update(kw)
    return rec


def test_a_shot_is_written_once(tmp_path):
    st = Store(tmp_path)
    assert st.put_shot(shot()) is True
    assert st.put_shot(shot()) is False  # the same record again: a no-op
    with pytest.raises(Conflict):
        st.put_shot(shot(energy_reported_j=11.0))
    assert len(st.shots()) == 1


def test_frames_round_trip_through_hdf5(tmp_path):
    st = Store(tmp_path, frames=True)
    img = (np.arange(64 * 64) % 4096).astype(np.uint16).reshape(64, 64)
    assert st.put_frames("S000-00001", 0, {"nf": img}, {"nf": {"exposure": 1.0}})
    assert not st.put_frames("S000-00001", 0, {"nf": img}, {})
    assert np.array_equal(st.frame(0, "S000-00001", "nf"), img)


def test_memory_bus_checks_message_types():
    bus = MemoryBus()
    bus.publish("lbp/shot", ShotMsg("S1", 0, 1.0, 10.0, 0, 0, 0, 0, 1.6))
    with pytest.raises(TypeError):
        bus.publish("lbp/interlock", ShotMsg("S1", 0, 1.0, 10.0, 0, 0, 0, 0, 1.6))


@pytest.mark.skipif(not HAVE_DDS, reason="cyclonedds not installed")
def test_dds_round_trip():
    from cyclonedds.domain import DomainParticipant
    from cyclonedds.sub import DataReader
    from cyclonedds.topic import Topic

    from lbp.bus.dds import DdsBus, InterlockMsg, qos_for

    bus = DdsBus(domain=0)
    dp = DomainParticipant(0)
    reader = DataReader(dp, Topic(dp, "lbp_interlock", InterlockMsg), qos=qos_for("lbp/interlock"))
    time.sleep(0.3)
    bus.publish("lbp/interlock", InterlockMsg("d-1", 0, 1.0, False, "predicted peak fluence above limit", 2.6))
    got = []
    for _ in range(20):
        got = reader.take()
        if got:
            break
        time.sleep(0.1)
    assert got and got[0].decision_id == "d-1" and not got[0].permit


def test_webhook_signature_and_replay_window():
    body = b'{"id":"e1"}'
    header = sign("s3cret", 1000, body)
    assert verify("s3cret", header, body, now=1010)
    assert not verify("other", header, body, now=1010)
    assert not verify("s3cret", header, b'{"id":"e2"}', now=1010)
    assert not verify("s3cret", header, body, now=5000)


def test_webhook_retries_with_backoff_and_deduplicates(cfg):
    now = {"t": 0.0}
    calls = []

    def sender(url, headers, body):
        calls.append(headers["X-LBP-Event-Id"])
        return 503 if len(calls) < 3 else 200

    d = Dispatcher(cfg, sender, clock=lambda: now["t"])
    sub = d.subscribe("https://lab.example/hook", ["interlock.held"])
    d.publish("interlock.held", "evt-1", {"permit": False})
    d.publish("interlock.held", "evt-1", {"permit": False})  # same event: queued once
    assert len(d.deliveries) == 1 and calls == ["evt-1"]
    for t in (0.5, 2.5):
        now["t"] = t
        d.pump()
    assert d.deliveries[0].status == "delivered" and d.deliveries[0].attempts == 3
    assert verify(sub.secret, sign(sub.secret, 2, d.deliveries[0].body), d.deliveries[0].body, now=2)


def test_webhook_gives_up_after_the_last_attempt(cfg):
    now = {"t": 0.0}
    d = Dispatcher(cfg, lambda *a: (_ for _ in ()).throw(ConnectionError()), clock=lambda: now["t"])
    d.subscribe("https://lab.example/hook", ["shot.stored"])
    d.publish("shot.stored", "evt-2", {})
    for _ in range(10):
        now["t"] += 60
        d.pump()
    assert d.deliveries[0].status == "failed"
    assert d.deliveries[0].attempts == cfg["webhooks"]["max_attempts"]


def test_webhook_rejects_unknown_events_and_plain_http(cfg):
    d = Dispatcher(cfg, lambda *a: 200)
    with pytest.raises(ValueError):
        d.subscribe("https://x.example", ["shot.deleted"])
    with pytest.raises(ValueError):
        d.subscribe("http://x.example", ["shot.stored"])


def test_api(tmp_path, monkeypatch, cfg):
    from fastapi.testclient import TestClient

    from lbp.api.app import ApiBus, Hub, create_app

    st = Store(tmp_path, frames=True)
    st.put_shot(shot())
    st.put_frames("S000-00001", 0, {"nf": np.full((32, 32), 500, dtype=np.uint16)}, {})
    hub = Hub()
    disp = Dispatcher(cfg, lambda *a: 200)
    client = TestClient(create_app(st, hub, disp))
    assert client.get("/api/shots").json()[0]["shot_id"] == "S000-00001"
    assert client.get("/api/shots/S999-00001").status_code == 404
    png = client.get("/api/shots/S000-00001/frames/nf.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert client.get("/api/shots/S000-00001/frames/ff.png").status_code == 404
    assert client.post("/api/webhooks", json={"url": "https://a.example", "events": ["shot.stored"]}).status_code == 401
    monkeypatch.setenv("LBP_API_TOKEN", "t0ken")
    auth = {"Authorization": "Bearer t0ken"}
    r = client.post("/api/webhooks", json={"url": "https://a.example", "events": ["shot.stored"]}, headers=auth)
    assert r.status_code == 201 and r.json()["secret"]
    ApiBus(hub, disp).publish("lbp/shot", ShotMsg("S000-00002", 0, 2.0, 10.0, 0, 0, 0, 0, 1.6))
    assert hub.latest["lbp/shot"]["shot_id"] == "S000-00002"
    assert disp.deliveries[-1].status == "delivered"
    assert client.delete(f"/api/webhooks/{r.json()['id']}", headers=auth).status_code == 204


def test_handover_checker_catches_numbers_that_are_not_in_the_facts(platform_day):
    from evals.operate import operate

    run = operate("platform", 11, days=1, store_root=None)
    f = handover.facts(run.ops.store, 0)
    text = handover.template_draft(f)
    assert handover.check(text, f).ok
    assert not handover.check(text.replace(str(f["shots_fired"]), str(f["shots_fired"] + 3), 1), f).ok
    assert not handover.check(text + "\nShot S000-99999 was the best.", f).ok
    assert json.dumps(f)
