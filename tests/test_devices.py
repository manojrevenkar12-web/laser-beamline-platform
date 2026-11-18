"""Drivers against the emulators: what may be retried, and what must never be repeated."""

from __future__ import annotations

import zlib

import numpy as np
import pytest

from lbp.devices.drivers import Camera, DeviceError, EnergyMeter, Laser, Picomotor, ReferenceMeter
from lbp.devices.transport import DeviceTimeout, LoopbackTransport, TcpTransport
from world.emulators import CameraServer, LaserController, NoReply, PicomotorController
from world.emulators import EnergyMeter as EmEmu
from world.emulators import ReferenceMeter as RefEmu


class LoseReplies:
    """Wrap an emulator: the device acts on the request, then the reply is lost."""

    def __init__(self, inner, lose: set[str]):
        self.inner, self.lose = inner, lose

    def handle(self, request: bytes) -> bytes:
        reply = self.inner.handle(request)
        if any(request.decode().startswith(x) for x in self.lose):
            self.lose = set()  # only once
            raise NoReply("lost")
        return reply


class DropFirst:
    """Wrap an emulator: the first matching request never reaches the device."""

    def __init__(self, inner, prefix: str):
        self.inner, self.prefix, self.done = inner, prefix, False

    def handle(self, request: bytes) -> bytes:
        if not self.done and request.decode().startswith(self.prefix):
            self.done = True
            raise NoReply("dropped")
        return self.inner.handle(request)


def test_a_lost_fire_reply_is_not_fired_again(line):
    laser = Laser("lcu", LoopbackTransport(LoseReplies(LaserController(line), {"FIRE:FULL"})))
    before = len([p for p in line.pulses if p.kind == "full"])
    pid = laser.fire_full(0.8)
    fulls = [p for p in line.pulses if p.kind == "full"]
    assert len(fulls) == before + 1  # one pulse, not two
    assert pid == fulls[-1].pulse_id
    assert laser.health.failures == 1


def test_a_dropped_move_is_resent_once_and_confirmed(line):
    pmc = Picomotor("pmc", LoopbackTransport(DropFirst(PicomotorController(line), "1PR")))
    assert pmc.move(0, 250) == 250
    assert int(line.commanded[0]) == 250  # the counter took exactly one move


def test_large_moves_are_chunked(line):
    pmc = Picomotor("pmc", LoopbackTransport(PicomotorController(line)))
    pmc.max_command = 1000
    assert pmc.move(2, -2500) == -2500
    assert int(line.commanded[2]) == -2500


def test_camera_retries_a_corrupted_frame(line):
    cam_emu = CameraServer(line, "nf")
    state = {"first": True}

    def corrupt_once() -> bool:
        first, state["first"] = state["first"], False
        return first

    cam_emu.faults.corrupt = corrupt_once  # type: ignore[method-assign]
    cam = Camera("nfc", LoopbackTransport(cam_emu))
    pulse = line.fire("low")
    frame = cam.frame(pulse.pulse_id, 1.0)
    assert frame.image.shape == (128, 128)
    assert cam.health.crc_errors == 1


def test_camera_frame_crc_and_header(line):
    cam = Camera("ffc", LoopbackTransport(CameraServer(line, "ff")))
    frame = cam.dark(1.0)
    assert frame.image.dtype == np.uint16 and frame.exposure == pytest.approx(1.0)
    assert zlib.crc32(frame.image.astype("<u2").tobytes()) >= 0


def test_unknown_pulse_is_a_device_error(line):
    cam = Camera("nfc", LoopbackTransport(CameraServer(line, "nf")))
    with pytest.raises(DeviceError):
        cam.frame(99999, 1.0)


def test_scpi_nan_reads_as_none(line):
    ref = ReferenceMeter("ref", LoopbackTransport(RefEmu(line)))
    line.fire("full", 0.8)
    assert ref.read() is None  # not flipped into the beam
    assert ref.due_day() == line.reference_due_day()
    em = EnergyMeter("em", LoopbackTransport(EmEmu(line)))
    assert em.read() == pytest.approx(line.pulses[-1].meter_raw_j, rel=1e-4)


def test_repeated_silence_faults_the_device(line):
    class Silent:
        def handle(self, request: bytes) -> bytes:
            raise NoReply("silent")

    em = EnergyMeter("em", LoopbackTransport(Silent()), retries=2)
    with pytest.raises(DeviceTimeout):
        em.read()
    assert em.health.faulted


def test_tcp_transport_against_a_device_server(line):
    from world.emulators import build
    from world.servers import serve

    ports, servers = serve(build(line))
    try:
        laser = Laser("lcu", TcpTransport("127.0.0.1", ports["lcu"], 1.0))
        cam = Camera("nfc", TcpTransport("127.0.0.1", ports["nfc"], 1.0))
        pid = laser.fire_low()
        frame = cam.frame(pid, 1.0)
        assert frame.image.shape == (128, 128) and frame.image.max() > 1000
        assert laser.diode_temp_c() > 0
    finally:
        for s in servers:
            s.shutdown()
            s.server_close()
