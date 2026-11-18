# Held-out campaign

`config/heldout.toml` was written before the platform was tuned on the dev beamlines and describes a beamline
it has not seen: other mount rotations and step sizes, about 1.7 times the backlash, an actuator that loses a
third of its step on day 6, a near-field camera that resets its gain by 1.6 on day 9, a reference meter whose
certificate expires on day 11, faster meter drift, more hot pixels, and hot spots on days 2 and 10.

`python3 -m evals.run --heldout` ran once, from a clean commit recorded in `reports/heldout.lock`. The results
are in the README and in `reports/heldout.json`. What happened is recorded below; the platform was not changed
because of it.

## What happened (run once at commit 2bc0686)

**Safe, but mostly holding.** The platform fired no damaging shot (the status quo fired 172 and had its optic
replaced twice), and 95.3 % of the shots it fired were in spec (status quo 16 %). But it fired only 12 shots
per shift on average, so it delivered 11.6 good shots per shift against the status quo's 20.4. Two gates
failed: good shots against the status quo (0.57, needs 1.5) and the energy reading error (1.75 %, needs 1.5 %).

Shift by shift, from `reports/heldout.json`:

1. **Shift 0, a false stuck-actuator fault.** The held-out controller silently skips a move 0.2 % of the time.
   One skipped 120-step poke during the matrix measurement made M1y look stuck, and the platform held every
   shot for the rest of the shift. One poke is not enough evidence: the stuck test must poke again before
   declaring a fault.
2. **Shift 1 was normal:** 153 shots, none held, 29 minutes of alignment against the larger backlash.
3. **Shift 2, the travel limit.** After the hot spot and the realignments around it, M2y reached the soft
   travel limit, and the platform held the shift. The limit counts steps from the start of the shift, and on
   this beamline the corrections are larger.
4. **Shifts 3 to 13, never recovered.** Each morning the beam started off a camera. The commissioning matrix
   could not find it in four tries, alignment ended outside tolerance three times, and the fault held the
   whole shift. Only the shifts with an energy cross-calibration fired anything (its ten shots).
5. **Energy.** The reference meter's certificate expired on shift 11 as planned. The platform refused to use
   it and raised an alert; the meter's faster drift then pushed the reading error to 1.75 %.

**The ablation that did better says where the problem is.** Without the matrix refresh, the platform delivered
107 good shots per shift at 94 % in spec, also with no damage. On this beamline the refresh was triggered by
mismatches the larger backlash produced, and it re-measured the matrix while the beam was far off, which made
things worse.

## Fixes this points to (not applied; a new held-out beamline is needed before claiming them)

- Confirm a stuck actuator with a second poke in both directions before the fault.
- Search for a lost beam instead of failing: a spiral over the commissioning matrix, or a wide-field
  alignment camera, before alignment counts as failed.
- Refresh the matrix only with the beam near the reference, and keep the old matrix if the new one predicts
  worse.
- On an alignment fault, ask the operators for a manual alignment and resume, instead of holding the shift.
- Warn about a reference certificate weeks before it expires, and widen the energy uncertainty instead of
  freezing the factor.
