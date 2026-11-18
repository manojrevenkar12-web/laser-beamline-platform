"""The platform's HTTP interface: shots, calibrations, alerts and live events for the operator console.

Reads come from the data store. Live state arrives through `ApiBus`, which the operations publish to; the
console subscribes with Server-Sent Events, and other systems with webhooks. Writes (webhook subscriptions)
need the bearer token in LBP_API_TOKEN.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import threading
from dataclasses import asdict, is_dataclass

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from lbp.api.webhooks import EVENTS, Dispatcher
from lbp.data.store import Store

TOPIC_EVENTS = {"lbp/shot": "shot.stored", "lbp/alignment": "alignment.done", "lbp/alert": "alert.raised"}


class Hub:
    """Fan-out of live messages to SSE listeners; keeps the latest message per topic for new listeners."""

    def __init__(self) -> None:
        self.latest: dict[str, dict] = {}
        self.listeners: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self.lock = threading.Lock()

    def push(self, topic: str, payload: dict) -> None:
        with self.lock:
            self.latest[topic] = payload
            listeners = list(self.listeners)
        for loop, q in listeners:
            loop.call_soon_threadsafe(q.put_nowait, (topic, payload))


class ApiBus:
    """The bus the operations publish to when the API runs: live events and webhooks."""

    def __init__(self, hub: Hub, dispatcher: Dispatcher | None = None):
        self.hub, self.dispatcher = hub, dispatcher
        self.count = 0

    def publish(self, topic: str, msg: object) -> None:
        payload = asdict(msg) if is_dataclass(msg) else dict(msg)  # type: ignore[arg-type]
        self.hub.push(topic, payload)
        if self.dispatcher is None:
            return
        self.count += 1
        if topic == "lbp/interlock" and not payload.get("permit", True):
            self.dispatcher.publish("interlock.held", f"interlock-{payload['decision_id']}", payload)
        elif topic in TOPIC_EVENTS:
            key = payload.get("shot_id") or payload.get("alert_id") or f"{payload.get('day')}-{payload.get('t_s')}"
            self.dispatcher.publish(TOPIC_EVENTS[topic], f"{TOPIC_EVENTS[topic]}-{key}", payload)


class WebhookIn(BaseModel):
    url: str
    events: list[str]


def png(image: np.ndarray) -> bytes:
    from PIL import Image

    lo, hi = np.percentile(image, 1), np.percentile(image, 99.9)
    scaled = np.clip((image.astype(float) - lo) / max(hi - lo, 1.0), 0, 1)
    buf = io.BytesIO()
    Image.fromarray((scaled * 255).astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def create_app(store: Store, hub: Hub | None = None, dispatcher: Dispatcher | None = None, status: dict | None = None) -> FastAPI:
    app = FastAPI(title="laser-beamline-platform", version="1.0.0")
    hub = hub or Hub()
    state = status if status is not None else {}

    def writer(authorization: str = Header(default="")) -> None:
        token = os.environ.get("LBP_API_TOKEN", "")
        if not token or authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="a bearer token is required to change subscriptions")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/status")
    def get_status() -> dict:
        shots = store.shots(limit=100000)
        return {
            "shots": len(shots),
            "last_shot": shots[-1] if shots else None,
            "latest": hub.latest,
            "devices": state.get("devices", []),
            "alignment_fault": state.get("alignment_fault", ""),
        }

    @app.get("/api/shots")
    def get_shots(day: int | None = None, purpose: str | None = None, limit: int = Query(500, le=5000)) -> list[dict]:
        return store.shots(day=day, purpose=purpose, limit=limit)

    @app.get("/api/shots/{shot_id}")
    def get_shot(shot_id: str) -> dict:
        rec = store.shot(shot_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"no shot {shot_id}")
        return rec

    @app.get("/api/shots/{shot_id}/frames/{camera}.png")
    def get_frame(shot_id: str, camera: str) -> Response:
        rec = store.shot(shot_id)
        if rec is None or camera not in ("nf", "ff"):
            raise HTTPException(status_code=404, detail="no such shot or camera")
        image = store.frame(rec["day"], shot_id, camera)
        if image is None:
            raise HTTPException(status_code=404, detail="frames are not stored for this shot")
        return Response(content=png(image), media_type="image/png")

    @app.get("/api/{table}")
    def get_table(table: str) -> list[dict]:
        if table not in ("decisions", "calibrations", "alignments", "alerts"):
            raise HTTPException(status_code=404, detail=f"no table {table}")
        rows = store.table(table)
        for r in rows:
            for k in ("summary", "reasons", "warnings"):
                if isinstance(r.get(k), str):
                    r[k] = json.loads(r[k])
        return rows

    @app.post("/api/webhooks", dependencies=[Depends(writer)], status_code=201)
    def add_webhook(body: WebhookIn) -> dict:
        if dispatcher is None:
            raise HTTPException(status_code=503, detail="webhooks are not configured")
        try:
            sub = dispatcher.subscribe(body.url, body.events)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": sub.sub_id, "url": sub.url, "events": list(sub.events), "secret": sub.secret}

    @app.delete("/api/webhooks/{sub_id}", dependencies=[Depends(writer)], status_code=204)
    def delete_webhook(sub_id: str) -> Response:
        if dispatcher is None or not dispatcher.unsubscribe(sub_id):
            raise HTTPException(status_code=404, detail=f"no subscription {sub_id}")
        return Response(status_code=204)

    @app.get("/api/webhooks/events")
    def webhook_events() -> list[str]:
        return list(EVENTS)

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        with hub.lock:
            hub.listeners.append((loop, q))
            snapshot = dict(hub.latest)

        async def stream():  # type: ignore[no-untyped-def]
            try:
                for topic, payload in snapshot.items():
                    yield f"event: {topic}\ndata: {json.dumps(payload, default=str)}\n\n"
                while True:
                    topic, payload = await q.get()
                    yield f"event: {topic}\ndata: {json.dumps(payload, default=str)}\n\n"
            finally:
                with hub.lock:
                    hub.listeners.remove((loop, q))

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
