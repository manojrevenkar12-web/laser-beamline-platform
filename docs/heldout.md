# Held-out campaign

`config/heldout.toml` was written before the platform was tuned on the dev beamlines and describes a beamline
it has not seen: other mount rotations and step sizes, about 1.7 times the backlash, an actuator that loses a
third of its step on day 6, a near-field camera that resets its gain by 1.6 on day 9, a reference meter whose
certificate expires on day 11, faster meter drift, more hot pixels, and hot spots on days 2 and 10.

`python3 -m evals.run --heldout` ran once, from a clean commit recorded in `reports/heldout.lock`. The results
are in the README and in `reports/heldout.json`. What happened is recorded below; the platform was not changed
because of it.
