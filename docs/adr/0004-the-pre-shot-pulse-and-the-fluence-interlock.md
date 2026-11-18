# 4. A pre-shot pulse, and a fluence interlock that code decides

## Context

A full shot through a hot spot (dust, a coating defect) or a clipped beam can exceed the damage fluence of an
optic, and a damage site grows on every later shot. An energy limit alone does not see this. The previous
shot's near-field image may be minutes old.

## Decision

Before each full shot the platform fires a front-end pulse at about 1/1000 of the energy and images it. That
pulse gives the current pointing and centring (realign if past 60 % of tolerance) and the current near-field
profile. The interlock (`lbp/control/interlocks.py`) is a pure function of what the platform knows: it predicts
the peak fluence from the target energy and the measured peak share of the profile and holds the shot above
75 % of the damage fluence, asking for an inspection. It also holds a shot with a faulted device, a stuck or
travel-limited alignment, a beam off the cameras, a pre-shot error beyond tolerance, a saturated profile or a
diode outside its band. Every decision is stored with its inputs and published on DDS.

## Consequences

The pre-shot pulse costs a few seconds per shot and catches a hot spot on the shot it appears. Without it, the
first shot after a hot spot appears fires on a stale profile. The interlock's only false holds so far would show
in "shots held while safe", which the evaluation counts against the truth.
