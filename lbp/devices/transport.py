"""How bytes reach a device: a TCP socket on the lab network, or an in-memory loopback for simulation.

Both carry the same requests and replies (docs/icd/), so a driver cannot tell them apart.
"""

from __future__ import annotations

import socket
import struct
from typing import Protocol

FRAME_MAGIC = b"LBPF"
FRAME_HEADER = struct.Struct("<4sIHHHfdI")


class DeviceTimeout(Exception):
    """The device did not answer within the timeout."""


class Transport(Protocol):
    def request(self, line: str, *, reply: bool = True) -> bytes: ...

    def close(self) -> None: ...


class LoopbackTransport:
    """Calls a device's handler directly. A handler that raises TimeoutError behaves like a silent device."""

    def __init__(self, handler: object):
        self.handler = handler

    def request(self, line: str, *, reply: bool = True) -> bytes:
        try:
            data = self.handler.handle((line + "\r\n").encode())  # type: ignore[attr-defined]
        except TimeoutError as exc:
            raise DeviceTimeout(line) from exc
        if reply and not data:
            raise DeviceTimeout(line)
        return data

    def close(self) -> None:
        return None


class TcpTransport:
    """One persistent connection per device. ASCII replies end in CR LF; frames start with the frame magic."""

    def __init__(self, host: str, port: int, timeout_s: float):
        self.addr, self.timeout_s = (host, port), timeout_s
        self.sock: socket.socket | None = None
        self.file = None

    def _connect(self) -> None:
        if self.sock is None:
            self.sock = socket.create_connection(self.addr, timeout=self.timeout_s)
            self.sock.settimeout(self.timeout_s)
            self.file = self.sock.makefile("rb")

    def _reset(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock, self.file = None, None

    def request(self, line: str, *, reply: bool = True) -> bytes:
        self._connect()
        assert self.sock is not None and self.file is not None
        try:
            self.sock.sendall((line + "\r\n").encode())
            if not reply:
                return b""
            head = self.file.read(4)
            if len(head) < 4:
                raise DeviceTimeout(line)
            if head == FRAME_MAGIC:
                rest = self.file.read(FRAME_HEADER.size - 4)
                _, _, w, h, _, _, _, _ = FRAME_HEADER.unpack(head + rest)
                payload = self.file.read(w * h * 2)
                return head + rest + payload
            return head + self.file.readline()
        except (TimeoutError, OSError) as exc:
            # a late reply would desynchronise the stream: start a fresh connection
            self._reset()
            raise DeviceTimeout(line) from exc

    def close(self) -> None:
        self._reset()
