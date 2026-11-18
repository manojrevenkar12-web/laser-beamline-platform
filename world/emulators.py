"""Device emulators: the beamline as its controllers, cameras and meters present it on the wire.

Each emulator turns one request (bytes) into one reply (bytes), following the interface documents in
docs/icd/. The same handler serves a TCP socket (world/servers.py) or an in-memory loopback for fast
evaluation, so the platform's drivers parse exactly the bytes a socket would carry.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

from world.beamline import Beamline, stream

FRAME_MAGIC = b"LBPF"
FRAME_HEADER = struct.Struct("<4sIHHHfdI")
SCPI_NAN = "9.91E+37"


class NoReply(TimeoutError):
    """The device stayed silent (a lost packet or a busy controller)."""


class Faults:
    """Link faults: a silent device or a corrupted frame, decided by the device's own stream."""

    def __init__(self, line: Beamline, device: str):
        self.line, self.device, self.count = line, device, 0
        self.p_timeout = float(line.cfg["link"]["timeout_prob"])
        self.p_crc = float(line.cfg["link"]["crc_error_prob"])

    def _rng(self) -> np.random.Generator:
        self.count += 1
        return stream(self.line.seed, "link", self.device, self.line.day, self.count)

    def maybe_timeout(self) -> None:
        if self._rng().random() < self.p_timeout:
            raise NoReply(self.device)

    def corrupt(self) -> bool:
        return bool(self._rng().random() < self.p_crc)


class PicomotorController:
    """A four-axis open-loop picomotor controller (ASCII, New Focus 8742 style)."""

    name = "pmc"

    def __init__(self, line: Beamline):
        self.line, self.faults = line, Faults(line, self.name)

    def handle(self, request: bytes) -> bytes:
        cmd = request.decode().strip()
        self.faults.maybe_timeout()
        if cmd == "*IDN?":
            return b"New_Focus 8742 v2.2 (simulated)\r\n"
        if cmd == "TB?":
            return b"0, NO ERROR DETECTED\r\n"
        if len(cmd) >= 3 and cmd[0] in "1234":
            axis = int(cmd[0]) - 1
            op = cmd[1:3]
            if op == "PR":
                steps = int(cmd[3:])
                if abs(steps) > 20000:
                    return b""
                self.line.move(axis, steps)
                return b""
            if op == "MD" and cmd.endswith("?"):
                return b"1\r\n"
            if op == "TP" and cmd.endswith("?"):
                return f"{int(self.line.commanded[axis])}\r\n".encode()
        return b""


class LaserController:
    """The laser's control unit: diode status, firing, the reference-meter flip mount and inspections."""

    name = "lcu"

    def __init__(self, line: Beamline):
        self.line, self.faults = line, Faults(line, self.name)
        self.last = None

    def handle(self, request: bytes) -> bytes:
        cmd = request.decode().strip()
        if cmd.startswith("FIRE:"):
            reply = self._fire(cmd)
            self.faults.maybe_timeout()  # the pulse has fired; only the reply is lost
            return reply
        self.faults.maybe_timeout()
        if cmd == "*IDN?":
            return b"LBP Laser Control Unit 1.4 (simulated)\r\n"
        if cmd == "PULSE?":
            return f"PULSE {self.line.pulse_count}\r\n".encode()
        if cmd == "STAT?":
            return b"READY\r\n"
        if cmd == "TEMP:DIODE?":
            return f"{self.line.diode_temp_c():.3f}\r\n".encode()
        if cmd.startswith("ROUT:REF "):
            self.line.reference_inserted = cmd.split()[1] == "1"
            self.line.advance(5.0)
            return b"OK\r\n"
        if cmd == "SERV:INSP":
            found = self.line.inspect_optics()
            return f"INSPECTED {found.upper()}\r\n".encode()
        return b"ERR UNKNOWN\r\n"

    def _fire(self, cmd: str) -> bytes:
        if cmd == "FIRE:LOW":
            self.last = self.line.fire("low")
            return f"PULSE {self.last.pulse_id}\r\n".encode()
        if cmd.startswith("FIRE:FULL "):
            pump = float(cmd.split()[1])
            if not 0.0 <= pump <= 1.2:
                return b"ERR RANGE\r\n"
            self.last = self.line.fire("full", pump)
            return f"PULSE {self.last.pulse_id}\r\n".encode()
        return b"ERR UNKNOWN\r\n"


class EnergyMeter:
    """A pyroelectric energy meter on the main pick-off (SCPI). Reads the last pulse."""

    name = "em"

    def __init__(self, line: Beamline):
        self.line, self.faults = line, Faults(line, self.name)

    def handle(self, request: bytes) -> bytes:
        cmd = request.decode().strip().upper()
        self.faults.maybe_timeout()
        if cmd == "*IDN?":
            return b"Pyro EM-50 (simulated)\r\n"
        if cmd == "MEAS:ENER?":
            last = self.line.pulses[-1] if self.line.pulses else None
            if last is None:
                return f"{SCPI_NAN}\r\n".encode()
            return f"{last.meter_raw_j:.5E}\r\n".encode()
        if cmd == "SYST:ERR?":
            return b'0,"No error"\r\n'
        return b'-113,"Undefined header"\r\n'


class ReferenceMeter:
    """A calibrated transfer-standard meter that reads only when flipped into the beam (SCPI)."""

    name = "ref"

    def __init__(self, line: Beamline):
        self.line, self.faults = line, Faults(line, self.name)

    def handle(self, request: bytes) -> bytes:
        cmd = request.decode().strip().upper()
        self.faults.maybe_timeout()
        if cmd == "*IDN?":
            return b"Reference calorimeter RC-10 (simulated)\r\n"
        if cmd == "MEAS:ENER?":
            last = self.line.pulses[-1] if self.line.pulses else None
            if last is None or last.reference_j is None:
                return f"{SCPI_NAN}\r\n".encode()
            return f"{last.reference_j:.5E}\r\n".encode()
        if cmd == "CAL:DUE?":
            return f"{self.line.reference_due_day()}\r\n".encode()
        if cmd == "CAL:UNC?":
            return f"{self.line.cfg['reference_meter']['uncertainty_k2']}\r\n".encode()
        return b'-113,"Undefined header"\r\n'


class CameraServer:
    """A 12-bit beam camera. ASCII requests, binary frames with a CRC-32 over the payload."""

    def __init__(self, line: Beamline, which: str):
        self.line, self.which = line, which
        self.name = f"{which}c"
        self.faults = Faults(line, self.name)
        self.frame_id = 0

    def _frame(self, image: np.ndarray, exposure: float) -> bytes:
        self.frame_id += 1
        payload = image.astype("<u2").tobytes()
        crc = zlib.crc32(payload)
        if self.faults.corrupt():
            buf = bytearray(payload)
            buf[len(buf) // 3] ^= 0x10
            payload = bytes(buf)
        stamp = self.line.day * 86400.0 + self.line.t
        h, w = image.shape
        return FRAME_HEADER.pack(FRAME_MAGIC, self.frame_id, w, h, 12, exposure, stamp, crc) + payload

    def handle(self, request: bytes) -> bytes:
        parts = request.decode().strip().split()
        self.faults.maybe_timeout()
        if not parts:
            return b"ERR EMPTY\r\n"
        if parts[0] == "*IDN?":
            return f"LBP BeamCam-{self.which.upper()} 12-bit (simulated)\r\n".encode()
        render = self.line.nf_image if self.which == "nf" else self.line.ff_image
        if parts[0] == "FRAME?" and len(parts) == 3:
            pulse_id, exposure = int(parts[1]), float(parts[2])
            pulse = next((p for p in reversed(self.line.pulses[-16:]) if p.pulse_id == pulse_id), None)
            if pulse is None or pulse_id not in self.line._profiles or not 0.01 <= exposure <= 4.0:
                return b"ERR FRAME\r\n"
            return self._frame(render(pulse, exposure), exposure)
        if parts[0] == "DARK?" and len(parts) == 2:
            exposure = float(parts[1])
            return self._frame(render(None, exposure), exposure)
        return b"ERR UNKNOWN\r\n"


def build(line: Beamline) -> dict[str, object]:
    """Every device on the beamline, by the name the platform's config uses."""
    return {
        "pmc": PicomotorController(line),
        "lcu": LaserController(line),
        "em": EnergyMeter(line),
        "ref": ReferenceMeter(line),
        "nfc": CameraServer(line, "nf"),
        "ffc": CameraServer(line, "ff"),
    }


class SimClock:
    """The campaign clock. Waiting advances the beamline's time; nothing else does except physical actions."""

    def __init__(self, line: Beamline):
        self.line = line

    def now(self) -> float:
        return self.line.day * 86400.0 + self.line.t

    def day(self) -> int:
        return self.line.day

    def seconds_into_day(self) -> float:
        return self.line.t

    def day_length(self) -> float:
        return self.line.day_s

    def sleep(self, seconds: float) -> None:
        self.line.advance(seconds)
