"""Webhooks: tell other systems when a shot is stored, an interlock holds a shot, an alert is raised or an
alignment finishes.

Each delivery carries an event id (receivers deduplicate on it) and an HMAC-SHA256 signature over the
timestamp and the body (`X-LBP-Signature: t=<unix>,v1=<hex>`). Failed deliveries are retried with the backoff
in config/platform.toml; after the last attempt the delivery is marked failed and kept for inspection.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

EVENTS = ("shot.stored", "interlock.held", "alert.raised", "alignment.done")


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify(secret: str, header: str, body: bytes, now: float | None = None, tolerance_s: float = 300.0) -> bool:
    """For receivers: check the signature and refuse replays older than the tolerance."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((now if now is not None else time.time()) - ts) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, ts, body), header)


@dataclass
class Subscription:
    sub_id: str
    url: str
    events: tuple[str, ...]
    secret: str


@dataclass
class Delivery:
    event_id: str
    sub_id: str
    event: str
    body: bytes
    attempts: int = 0
    status: str = "pending"  # pending, delivered, failed
    last_error: str = ""
    next_at: float = 0.0
    history: list[dict] = field(default_factory=list)


# a sender posts (url, headers, body) and returns the HTTP status code; it raises on a network error
Sender = Callable[[str, dict[str, str], bytes], int]


class Dispatcher:
    def __init__(self, cfg: dict, sender: Sender, clock: Callable[[], float] = time.time):
        self.cfg, self.sender, self.clock = cfg, sender, clock
        self.subs: dict[str, Subscription] = {}
        self.deliveries: list[Delivery] = []
        self._ids = itertools.count(1)

    def subscribe(self, url: str, events: list[str]) -> Subscription:
        unknown = [e for e in events if e not in EVENTS]
        if unknown:
            raise ValueError(f"unknown events: {unknown}")
        if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("webhook URLs must be https (or local for development)")
        sub = Subscription(f"wh-{next(self._ids):04d}", url, tuple(events), secrets.token_hex(16))
        self.subs[sub.sub_id] = sub
        return sub

    def unsubscribe(self, sub_id: str) -> bool:
        return self.subs.pop(sub_id, None) is not None

    def publish(self, event: str, event_id: str, data: dict) -> list[Delivery]:
        out = []
        for sub in self.subs.values():
            if event not in sub.events:
                continue
            if any(d.event_id == event_id and d.sub_id == sub.sub_id for d in self.deliveries):
                continue  # the same event is queued once per subscription
            body = json.dumps({"id": event_id, "type": event, "data": data}, sort_keys=True, default=str).encode()
            d = Delivery(event_id, sub.sub_id, event, body, next_at=self.clock())
            self.deliveries.append(d)
            out.append(d)
        self.pump()
        return out

    def pump(self) -> None:
        """Attempt every delivery that is due."""
        backoff = [float(x) for x in self.cfg["webhooks"]["backoff_s"]]
        max_attempts = int(self.cfg["webhooks"]["max_attempts"])
        now = self.clock()
        for d in self.deliveries:
            if d.status != "pending" or d.next_at > now:
                continue
            sub = self.subs.get(d.sub_id)
            if sub is None:
                d.status, d.last_error = "failed", "subscription removed"
                continue
            ts = int(now)
            headers = {
                "Content-Type": "application/json",
                "X-LBP-Event": d.event,
                "X-LBP-Event-Id": d.event_id,
                "X-LBP-Signature": sign(sub.secret, ts, d.body),
            }
            d.attempts += 1
            try:
                code = self.sender(sub.url, headers, d.body)
                ok, err = 200 <= code < 300, f"HTTP {code}"
            except Exception as exc:  # network errors are retried like 5xx
                ok, err = False, type(exc).__name__
            d.history.append({"at": now, "ok": ok, "error": "" if ok else err})
            if ok:
                d.status = "delivered"
            elif d.attempts >= max_attempts:
                d.status, d.last_error = "failed", err
            else:
                d.last_error = err
                d.next_at = now + backoff[min(d.attempts - 1, len(backoff) - 1)]


def http_sender(timeout_s: float) -> Sender:
    import httpx

    def send(url: str, headers: dict[str, str], body: bytes) -> int:
        return httpx.post(url, content=body, headers=headers, timeout=timeout_s).status_code

    return send
