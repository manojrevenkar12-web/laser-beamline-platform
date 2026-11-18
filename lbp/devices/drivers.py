"""Drivers for the beamline's devices, written from the interface documents in docs/icd/.

Every driver retries only what is safe to repeat. A frame or a reading can be asked for again. A move is
confirmed against the controller's step counter before it is resent, and a fire command is never repeated
blindly: after a lost reply the driver asks the controller which pulse it fired last.
"""

from __future__ import annotations

import time
import zlib
from dataclasses import dataclass, field

import numpy as np

from lbp.devices.transport import FRAME_HEADER, FRAME_MAGIC, DeviceTimeout, Transport

SCPI_NAN = 9.9e37


class DeviceError(Exception):
    """The device answered, but not with what the interface document promises."""


@dataclass
class Health:
    name: str
    ok: int = 0
    failures: int = 0
    consecutive: int = 0
    crc_errors: int = 0
    last_error: str = ""
    fault_after: int = 3

    @property
    def faulted(self) -> bool:
        return self.consecutive >= self.fault_after

    def success(self) -> None:
        self.ok += 1
        self.consecutive = 0

    def failure(self, why: str) -> None:
        self.failures += 1
        self.consecutive += 1
        self.last_error = why

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "failures": self.failures,
            "crc_errors": self.crc_errors,
            "faulted": self.faulted,
            "last_error": self.last_error,
        }


@dataclass
class Device:
    name: str
    transport: Transport
    retries: int = 2
    health: Health = field(init=False)

    def __post_init__(self) -> None:
        self.health = Health(self.name)

    def query(self, line: str) -> str:
        """A request that is safe to repeat."""
        last: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                text = self.transport.request(line).decode(errors="replace").strip()
                self.health.success()
                return text
            except DeviceTimeout as exc:
                self.health.failure(f"timeout: {line}")
                last = exc
        raise DeviceTimeout(f"{self.name}: {line}") from last

    def write(self, line: str) -> bool:
        """A command without a reply. Returns False when the link reported a failure."""
        try:
            self.transport.request(line, reply=False)
            return True
        except DeviceTimeout:
            self.health.failure(f"lost: {line}")
            return False


class Picomotor(Device):
    """Open-loop picomotor controller. Axes are numbered 1 to 4 on the wire, 0 to 3 here."""

    max_command: int = 4000

    def position(self, axis: int) -> int:
        return int(self.query(f"{axis + 1}TP?"))

    def move(self, axis: int, steps: int) -> int:
        """Move by `steps` and confirm against the step counter. Returns the steps the controller counted."""
        if steps == 0:
            return 0
        done = 0
        remaining = steps
        while remaining != 0:
            chunk = max(-self.max_command, min(self.max_command, remaining))
            before = self.position(axis)
            for _ in range(self.retries + 1):
                self.write(f"{axis + 1}PR{chunk}")
                self.query(f"{axis + 1}MD?")
                after = self.position(axis)
                if after - before == chunk:
                    break
                if after != before:
                    raise DeviceError(f"{self.name}: axis {axis + 1} counted {after - before} of {chunk}")
            else:
                raise DeviceError(f"{self.name}: axis {axis + 1} did not take the move")
            done += chunk
            remaining -= chunk
        return done


class Laser(Device):
    def diode_temp_c(self) -> float:
        return float(self.query("TEMP:DIODE?"))

    def status(self) -> str:
        return self.query("STAT?")

    def _last_pulse(self) -> int:
        reply = self.query("PULSE?")
        return int(reply.split()[1])

    def _fire(self, line: str) -> int:
        before = self._last_pulse()
        try:
            reply = self.transport.request(line).decode().strip()
            self.health.success()
        except DeviceTimeout:
            self.health.failure(f"lost reply: {line}")
            after = self._last_pulse()
            if after > before:
                return after  # it fired; the reply was lost
            raise DeviceError(f"{self.name}: no pulse after {line}") from None
        if not reply.startswith("PULSE "):
            raise DeviceError(f"{self.name}: {line} -> {reply}")
        return int(reply.split()[1])

    def fire_low(self) -> int:
        return self._fire("FIRE:LOW")

    def fire_full(self, pump: float) -> int:
        return self._fire(f"FIRE:FULL {pump:.4f}")

    def reference(self, inserted: bool) -> None:
        if self.query(f"ROUT:REF {1 if inserted else 0}") != "OK":
            raise DeviceError(f"{self.name}: flip mount")

    def inspect(self) -> str:
        """Ask the technicians for an optics inspection; returns "damage", "hotspot" or "clean"."""
        reply = self.query("SERV:INSP")
        if not reply.startswith("INSPECTED "):
            raise DeviceError(f"{self.name}: {reply}")
        return reply.split()[1].lower()


class EnergyMeter(Device):
    def read(self) -> float | None:
        value = float(self.query("MEAS:ENER?"))
        return None if value >= SCPI_NAN else value


class ReferenceMeter(EnergyMeter):
    def due_day(self) -> int:
        return int(self.query("CAL:DUE?"))

    def uncertainty_k2(self) -> float:
        return float(self.query("CAL:UNC?"))


@dataclass
class Frame:
    image: np.ndarray
    frame_id: int
    exposure: float
    stamp: float


class Camera(Device):
    def _parse(self, data: bytes) -> Frame:
        if data[:4] != FRAME_MAGIC:
            raise DeviceError(f"{self.name}: {data[:60]!r}")
        magic, frame_id, w, h, bits, exposure, stamp, crc = FRAME_HEADER.unpack(data[: FRAME_HEADER.size])
        payload = data[FRAME_HEADER.size :]
        if bits != 12 or len(payload) != w * h * 2:
            raise DeviceError(f"{self.name}: frame size")
        if zlib.crc32(payload) != crc:
            self.health.crc_errors += 1
            raise ValueError("crc")
        image = np.frombuffer(payload, dtype="<u2").reshape(h, w).astype(np.uint16)
        return Frame(image, frame_id, float(exposure), float(stamp))

    def _get(self, line: str) -> Frame:
        for _ in range(self.retries + 2):
            try:
                data = self.transport.request(line)
            except DeviceTimeout:
                self.health.failure(f"timeout: {line}")
                continue
            try:
                frame = self._parse(data)
            except ValueError:
                self.health.failure(f"crc: {line}")
                continue
            self.health.success()
            return frame
        raise DeviceTimeout(f"{self.name}: {line}")

    def frame(self, pulse_id: int, exposure: float) -> Frame:
        return self._get(f"FRAME? {pulse_id} {exposure:.4f}")

    def dark(self, exposure: float) -> Frame:
        return self._get(f"DARK? {exposure:.4f}")


class WallClock:
    """The real clock, for a beamline on the network."""

    def now(self) -> float:
        return time.time()

    def day(self) -> int:
        return int(time.time() // 86400)

    def seconds_into_day(self) -> float:
        return time.time() % 86400

    def day_length(self) -> float:
        return 8 * 3600.0

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
