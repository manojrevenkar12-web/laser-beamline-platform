# 1. The truth stays behind the device protocols

## Context

A laser-software platform is built before the laser exists, and it must still be tested against something that
behaves like hardware: drifting tables, mounts with backlash, cameras with hot pixels, meters that lose
sensitivity, optics that damage. If the code under test can read the simulator's state, every test passes for
the wrong reason.

## Decision

The simulated beamline (`world/`) holds the truth. The platform (`lbp/`) reaches it only through the device
protocols in `docs/icd/devices.md`: ASCII and SCPI requests, binary camera frames with a CRC. Loopback and TCP
transports carry the same bytes. Only `evals/` sees both sides, to score a run. A test fails the build if
`lbp/` imports `world/` or `evals/`.

## Consequences

The drivers, retries and parsers are exercised on every evaluation run, not only in a system test. Swapping an
emulator for a real controller changes a host and a port. The world can model things the platform cannot see
(true mirror angles, true fluence), and the evaluation can say how wrong the platform's view was.
