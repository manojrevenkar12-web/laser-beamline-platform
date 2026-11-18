# Working on this repository (people and coding agents)

## Fast feedback

```bash
scripts/check.sh                          # build beamcore, C++ tests, lint, Python tests (about a minute)
python3 -m evals.run --days 3             # every design on the dev beamlines for three shifts (not written)
python3 -m evals.run                      # the full dev campaign -> reports/dev.json (about six minutes)
python3 -m evals.readme                   # regenerate the README's results from reports/
```

## Invariants (each has a test or a gate)

- **The truth stays in the world.** `world/` holds the beamline's state. `lbp/` reaches it only through the
  device protocols in `docs/icd/devices.md` and never imports `world/` or `evals/` (`tests/test_invariants.py`).
  Only `evals/` sees both sides, to score a run.
- **The world does not read the platform's settings.** `world/` reads `config/world.toml` or
  `config/heldout.toml`, never `config/platform.toml` or `config/designs.toml`.
- **Same luck for every design.** Every random draw in the world comes from a stream keyed by the seed, a name,
  the day and the time. Drift, hot spots, hot pixels and wear do not depend on what a design does.
- **The model reads, code decides.** Interlocks, alignment and calibration decisions are code. A model may
  draft the shift handover; `lbp/elog/handover.check` refuses any number or shot id the data does not back.
- **A shot fires only through the interlocks.** `Operations._fire` is reached only after `evaluate` permits;
  every decision is stored with its inputs. A fire command is never repeated after a lost reply.
- **A shot is stored once.** The same record again is a no-op; a different record under the same id is refused.
- **Settings live in config.** Thresholds, tolerances and timings are in `config/platform.toml`. A test fails on
  a setting nobody reads and on a decimal literal in `lbp/control` or `lbp/calibration`.
- **Reports are generated.** `reports/*.json` come from `evals/`; the README's results block comes from
  `evals/readme.py`. Never edit either by hand; CI checks the README is current.

## Held-out rule

`config/heldout.toml` describes a beamline the platform was not tuned on. `python3 -m evals.run --heldout` runs
it once: it refuses to start with uncommitted platform changes, writes `reports/heldout.lock` with the commit,
and refuses to run again once `reports/heldout.json` exists. Never change the platform to pass the held-out
campaign. If you study its failures, say so in `docs/heldout.md` and write a new held-out beamline before
claiming anything about the fix.

## Where things are

| Path | What |
|---|---|
| `world/` | the simulated beamline (truth), device emulators, TCP servers |
| `lbp/devices/` | transports (loopback, TCP) and drivers |
| `lbp/diagnostics/` | ISO 11146 analysis (NumPy reference) and the C++ engine wrapper |
| `cpp/beamcore/` | the C++ engine, its bindings and tests |
| `lbp/calibration/` | dark frames and hot pixels, the interaction matrix and alignment, energy cross-calibration |
| `lbp/control/` | interlocks and the shift and shot cycle |
| `lbp/data/` | SQLite shot records, HDF5 frames |
| `lbp/bus/`, `lbp/api/` | DDS topics, HTTP API, Server-Sent Events, webhooks |
| `lbp/elog/` | shift handover for the logbook, and its checker |
| `evals/` | run designs, score against the truth, gates, README, console data |
| `web/` | the operator console (React, TypeScript, Framer Motion) |
| `docs/` | ADRs, interface documents, assumptions, held-out notes |
