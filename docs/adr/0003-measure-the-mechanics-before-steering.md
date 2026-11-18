# 3. Measure the mechanics before steering

## Context

Two picomotor-driven mirrors steer the beam onto the amplifier aperture and into the target chamber. The
drawings give a commissioning matrix, but real mounts are rotated, their steps differ forward and reverse, they
lose tens of steps on every change of direction, and an actuator can wear. The near field barely moves for a
poke small enough to keep the far-field spot on its camera, so a naive poke-based matrix has noisy near-field
rows, and the two mirrors then fight each other.

## Decision

The interaction matrix is measured on the beamline: each axis is loaded forward, poked forward and twice
backward, which gives its column, its backlash and its reverse-to-forward ratio. The near-field rows are then
re-measured along the centring walks (moves of both mirrors that hold the pointing), which can be large. Moves
add the backlash after a reversal and scale reverse steps. Corrections are damped least squares weighted by the
tolerances and shortened to a step cap, so step-size scatter cannot walk the spot off a camera. A move that
does not do what the matrix predicts, twice, triggers a fresh measurement; a column far below the drawing's
means the actuator is stuck, and alignment stops with a reason. A soft travel limit and a fault after three
alignments that end outside tolerance keep a confused loop from driving the mirrors away.

## Consequences

About two minutes of the first shift go into calibration. The ablations show what each part is worth:
without backlash compensation the platform loses about a third of its good shots; the matrix refresh matters
most on the held-out beamline, where an actuator wears.
