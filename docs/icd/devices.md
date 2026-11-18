# Device interfaces

The platform talks to every device through these interfaces; the emulators in `world/emulators.py` implement
them, and so would the real devices or their vendor gateways. Requests are ASCII lines ending in CR LF. One
TCP connection per device; `config/platform.toml [devices]` sets timeouts, retries and when a device counts as
faulted.

## Picomotor controller (`pmc`), four open-loop axes

| Request | Reply | Notes |
|---|---|---|
| `*IDN?` | identity line | |
| `nPRs` | none | relative move of `s` steps on axis `n` (1 to 4); \|s\| ≤ 20000 |
| `nMD?` | `1` when motion is done | |
| `nTP?` | commanded step counter | open loop: counts what was commanded, not where the mirror is |
| `TB?` | `0, NO ERROR DETECTED` | |

A move has no reply, so a lost command is only visible in the step counter. The driver reads `nTP?` before and
after, resends only when the counter did not change, and refuses a partial count.

## Laser control unit (`lcu`)

| Request | Reply | Notes |
|---|---|---|
| `STAT?` | `READY` | |
| `TEMP:DIODE?` | `25.130` | diode temperature, °C |
| `FIRE:LOW` | `PULSE <id>` | front-end pulse, about 1/1000 of full energy, for alignment |
| `FIRE:FULL <pump>` | `PULSE <id>` or `ERR RANGE` | pump 0 to 1.2 |
| `PULSE?` | `PULSE <id>` | the last pulse fired |
| `ROUT:REF 0\|1` | `OK` | flips the reference meter into the beam |
| `SERV:INSP` | `INSPECTED CLEAN\|HOTSPOT\|DAMAGE` | an optics inspection by the technicians; takes the beamline down |

A fire command is never repeated after a lost reply: the driver asks `PULSE?` and compares it with the count
before the command.

## Energy meters (`em` on the pick-off, `ref` the transfer standard), SCPI

| Request | Reply |
|---|---|
| `MEAS:ENER?` | energy of the last pulse in J, `9.91E+37` when there is none |
| `CAL:DUE?` (`ref` only) | day the certificate expires |
| `CAL:UNC?` (`ref` only) | expanded relative uncertainty (k = 2) |

## Beam cameras (`nfc` near field, `ffc` far field), 12 bit

| Request | Reply |
|---|---|
| `FRAME? <pulse_id> <exposure>` | binary frame of that pulse |
| `DARK? <exposure>` | binary frame with no pulse |

Binary frame: header `<4sIHHHfdI` little-endian (magic `LBPF`, frame id, width, height, bits = 12, exposure,
timestamp in s, CRC-32 of the payload), then width × height `uint16` little-endian. A CRC mismatch is retried.
