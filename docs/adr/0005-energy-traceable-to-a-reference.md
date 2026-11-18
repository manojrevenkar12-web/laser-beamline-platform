# 5. Energy readings traceable to a reference meter

## Context

The pick-off pyroelectric meter loses sensitivity steadily, a few tenths of a per cent per day. The energy
loop uses its readings, so an uncorrected drift becomes an energy error on target and a fluence error on the
optics.

## Decision

Every three shifts the platform flips a reference meter with a valid certificate into the beam and takes ten
paired readings. The new factor is applied only if its expanded uncertainty (scatter of the ratios and the
certificate, k = 2) is within 1.5 %. The drift seen between the last two cross-calibrations is extrapolated
between them. A reference past its due date is refused with an alert; readings older than seven days are
flagged as not traceable.

## Consequences

Thirty minutes every third shift. The held-out beamline's reference certificate expires on day 11, so the last
days run on an extrapolated factor; the report shows what that costs.
