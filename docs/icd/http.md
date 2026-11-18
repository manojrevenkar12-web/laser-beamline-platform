# HTTP interface and webhooks

`lbp/api/app.py` (FastAPI). Reads are open on the lab network; changing webhook subscriptions needs
`Authorization: Bearer $LBP_API_TOKEN`.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{"ok": true}` |
| GET | `/api/status` | shot count, last shot, latest message per topic, device health, alignment fault |
| GET | `/api/shots?day=&purpose=&limit=` | shot records with the calibration ids behind each number |
| GET | `/api/shots/{id}` | one shot, 404 if unknown |
| GET | `/api/shots/{id}/frames/{nf\|ff}.png` | the stored camera frame, 404 if frames were not kept |
| GET | `/api/decisions`, `/api/calibrations`, `/api/alignments`, `/api/alerts` | the tables |
| GET | `/api/events` | Server-Sent Events: `lbp/shot`, `lbp/interlock`, `lbp/alignment`, `lbp/alert`, `lbp/health` |
| POST | `/api/webhooks` | `{"url", "events"}` → 201 with the subscription id and its signing secret |
| DELETE | `/api/webhooks/{id}` | 204 |

## Webhooks

Events: `shot.stored`, `interlock.held`, `alignment.done`, `alert.raised`. Body:
`{"id": <event id>, "type": <event>, "data": {...}}`. Headers: `X-LBP-Event`, `X-LBP-Event-Id` (deduplicate on
it) and `X-LBP-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>." + body>`. Verify with
`lbp.api.webhooks.verify`, which also refuses signatures older than five minutes. Failed deliveries are retried
after 0.5, 2, 8 and 30 s, then marked failed. URLs must be https (or localhost for development).
