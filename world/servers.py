"""TCP servers for the emulators: the beamline on real sockets, one port per device.

A request is one line ending in CR LF. The reply is whatever the emulator returns (an ASCII line, a binary
frame, or nothing). A silent device sends nothing and the client's timeout decides.
"""

from __future__ import annotations

import socketserver
import threading

from world.emulators import NoReply


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server: DeviceServer = self.server  # type: ignore[assignment]
        while True:
            line = self.rfile.readline()
            if not line:
                return
            with server.lock:
                try:
                    reply = server.device.handle(line)
                except NoReply:
                    continue
            if reply:
                self.wfile.write(reply)
                self.wfile.flush()


class DeviceServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, device: object, lock: threading.Lock, host: str = "127.0.0.1", port: int = 0):
        self.device, self.lock = device, lock
        super().__init__((host, port), _Handler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])


def serve(devices: dict[str, object], host: str = "127.0.0.1") -> tuple[dict[str, int], list[DeviceServer]]:
    """Start one server per device on free ports; returns the port map and the servers to shut down."""
    lock = threading.Lock()
    servers, ports = [], {}
    for name, device in devices.items():
        s = DeviceServer(device, lock, host)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
        ports[name] = s.port
    return ports, servers
