# laser-beamline-platform

**A greenfield software platform for a laser team, built and tested against a simulated beamline. It covers
device drivers for the controllers, cameras and energy meters; ISO 11146 beam diagnostics in C++; automated
alignment and calibration; a shot sequencer whose interlocks predict the fluence on the optics; experimental
data in HDF5 and SQLite; DDS, REST and webhooks; and an operator console.**

![The operator console: the beamline, the interlocks, the near- and far-field cameras and a shift's pointing](docs/console.png)

A laser team's day has the same problems every shift. The table drifts, so someone realigns two mirrors by hand
while watching camera screens. Mounts lose motion when they change direction. Cameras have hot pixels and
background light. The energy meter slowly loses sensitivity. Now and then dust on an optic makes a hot spot that
the next full-energy shot burns in, and that damage site grows with every later shot. This repository is the
software that takes over those jobs and records why it did each thing. Because the laser it targets does not
exist yet, it is tested against a simulated beamline with a hidden truth. Every design is scored on the same
luck: the same drift, the same hot spots, the same shot-to-shot jitter.

## Results

<!-- results:start -->
_No results yet: run `python3 -m evals.run`._
<!-- results:end -->

![Good shots per shift for every design](docs/charts/designs.png)

![One shift on dev beamline 11: the status quo fires into a hot spot and drifts; the platform holds one shot, asks for an inspection and stays inside tolerance](docs/charts/shift.png)

## What it does

| Area | What is here |
|---|---|
| **Device layer** | Drivers for a four-axis picomotor controller (ASCII), the laser control unit, two SCPI energy meters and two 12-bit cameras (binary frames with CRC-32). They work over TCP or an in-memory loopback that carries the same bytes. Only safe-to-repeat requests are retried. A move is confirmed against the controller's step counter. A FIRE command is never repeated after a lost reply. Device health counts failures and CRC retries, and a faulted device holds the shots. ([docs/icd/devices.md](docs/icd/devices.md)) |
| **Diagnostics** | ISO 11146 beam analysis: dark frame and border baseline, hot-pixel map (median absolute deviation against the local background), iterated integration area of three beam widths, D4σ widths, a 3×3 peak, saturation that ignores isolated hot pixels. It is written in C++20 (`cpp/beamcore`, pybind11) and as a NumPy reference, kept identical by a property test on random frames. |
| **Calibration** | The interaction matrix is measured on the beamline: per-axis pokes give the pointing rows, backlash and the reverse/forward step ratio, and centring walks give the near-field rows. Alignment uses damped least squares weighted by the tolerances and shortens any step that could push the spot off a camera. It backs off a move that loses the beam, refreshes the matrix after repeated mismatch, detects a stuck actuator, enforces a soft travel limit, and faults after repeated non-convergence. Exposure control and dark frames run every shift. Energy-meter cross-calibration uses a reference with a certificate, an uncertainty budget (k = 2) and drift extrapolation. ([ADR 3](docs/adr/0003-measure-the-mechanics-before-steering.md), [ADR 5](docs/adr/0005-energy-traceable-to-a-reference.md)) |
| **Shot sequencer and interlocks** | Each shot starts with a pre-shot pulse at about 1/1000 of full energy. The platform realigns on condition, then asks the interlocks. They predict the peak fluence from the measured near-field profile and the target energy, and they check device faults, alignment faults, a beam off the cameras, a pre-shot error beyond tolerance, saturation and the diode temperature. Shots above 8 J carry a second person's confirmation. Every decision is stored with its inputs. ([ADR 4](docs/adr/0004-the-pre-shot-pulse-and-the-fluence-interlock.md)) |
| **Data** | Shot records go to SQLite and are written once: the same record again is a no-op, a different one is refused. Each record carries the ids of the camera, matrix and energy calibrations behind its numbers. Frames go to HDF5, chunked and gzip-compressed, one file per shift. |
| **Interfaces** | DDS topics on Eclipse Cyclone DDS (shots, interlock state as transient-local, alignments, alerts, health); a FastAPI service with Server-Sent Events; webhooks with HMAC-SHA256 signatures, replay window, retries with backoff and event ids for deduplication. ([docs/icd/dds.md](docs/icd/dds.md), [docs/icd/http.md](docs/icd/http.md)) |
| **Logbook agent** | At the end of a shift, a model drafts the handover note (with `ANTHROPIC_API_KEY` set; a template otherwise) from facts the data store can prove. Code checks every number and shot id before the note posts. ([ADR 6](docs/adr/0006-the-model-drafts-code-checks-the-logbook.md)) |
| **Operator console** | React, TypeScript and Framer Motion. Three views: the beamline with device health; the interlock state with every held shot and its reasons; and camera frames with the reference, tolerance and measured D4σ ellipse, the shift's pointing, the calibration history and the evaluation. Each view has loading, error-with-retry and empty states. |

## How it works

```
                 config/world.toml (truth)                          config/platform.toml, designs.toml
 world/beamline.py ── mirrors, drift, cameras, meters, hot spots, damage
        │
 world/emulators.py ── the devices as they look on the wire (ASCII, SCPI, binary frames)
        │  loopback or TCP (world/servers.py)
 lbp/devices ── drivers: retry what is safe, confirm moves, never re-fire, CRC, health
        │
 lbp/diagnostics ── ISO 11146 (C++ beamcore = NumPy reference)
 lbp/calibration ── dark + hot pixels, exposure, interaction matrix + backlash, alignment, energy cross-cal
 lbp/control     ── shift: dark frames, cross-cal when due, matrix, align
                    shot: pre-shot pulse → realign on condition → interlocks → fire → measure → store
 lbp/data        ── SQLite shots/decisions/calibrations, HDF5 frames
 lbp/bus, lbp/api ── DDS topics, REST + SSE, signed webhooks ──► web/ operator console
 lbp/elog        ── handover draft (model or template) → number check → logbook
        │
 evals/ ── operate designs on the same luck, score against the truth, gates, held-out once, README
```

## Limits: what is simulated

- **The beamline is simulated.** That covers the mirror geometry, step sizes and backlash, drift and warm-up,
  the cameras' noise and defects, the meters' drift, hot spots and damage growth. The numbers are chosen to be
  plausible, not measured on Focused Energy's lasers. The platform never reads the simulation's state, but its
  tuning (tolerances, the realignment threshold, step caps) was set on the dev beamlines.
- **The devices are emulators.** They speak documented, realistic protocols, not any vendor's exact command
  set. A real controller needs a driver adapted to its manual, with the same safety rules.
- **One laser chain, two mirrors, two cameras.** No timing system, no PLC or SCADA interface (DDS and REST are
  the integration points here), no multi-beam coordination.
- **The status quo is a model of manual operation.** An operator aligns by eye on the camera screens with the
  commissioning matrix and checks the optics every morning. Real teams differ.
- **Some ablations have no measurable effect on the dev beamlines.** Exposure control, the matrix refresh and
  the hot-pixel map barely change the dev numbers; the held-out beamline (camera gain reset, actuator wear) is
  where they are tested. Without dark-frame subtraction the far-field spot cannot be measured at all, so that
  ablation fires nothing.
- **No model ran in this build.** The handover evaluation measures the checker on template drafts with planted
  errors. A wrong number that happens to equal another fact of the same shift passes the check; that is the
  main miss in the table above.

## Run it

```bash
pip install -r requirements.txt
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j   # beamcore + its tests + the Python module
scripts/check.sh                    # C++ tests, lint, Python tests, README check
python3 -m evals.run --days 3       # every design on the dev beamlines for three shifts
python3 -m evals.run                # the full dev campaign -> reports/dev.json
python3 -m evals.readme             # regenerate the results above

cd web && npm ci && npm run dev     # the console, on data from python3 -m evals.console_data
```

Repository rules for people and coding agents: [AGENTS.md](AGENTS.md). Repeatable tasks: [SKILLS.md](SKILLS.md).
Decisions: [docs/adr](docs/adr). Held-out notes: [docs/heldout.md](docs/heldout.md).
