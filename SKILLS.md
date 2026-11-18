# Repeatable tasks

## Add a device

1. Write its interface in `docs/icd/devices.md` (requests, replies, which requests are safe to repeat).
2. Add an emulator to `world/emulators.py` that follows it, including its failure modes.
3. Add a driver to `lbp/devices/drivers.py`: retry only what is idempotent; confirm side effects by reading
   state back (as the picomotor driver does with the step counter).
4. Register it in `evals/operate.py` and test it in `tests/test_devices.py` over loopback and TCP.

## Add an interlock rule

1. Add the input to `ShotInputs` and the rule to `evaluate` in `lbp/control/interlocks.py`, with a reason that
   names the numbers. Its threshold goes in `config/platform.toml`.
2. Fill the input in `Operations._inputs`.
3. Add a case to `test_each_rule_says_why` and run `python3 -m evals.run --days 3`: "shots held while safe" must
   not rise.

## Add a design or an ablation

Add a section to `config/designs.toml` (`base = "platform"` and the flags that differ). Run
`python3 -m evals.run`, then `python3 -m evals.readme`.

## Change the beam analysis

Change `lbp/diagnostics/beam.py` and `cpp/beamcore/src/beamcore.cpp` together. `pytest tests/test_diagnostics.py`
runs the property test that keeps them identical; `python3 scripts/bench.py` updates the speed table.

## Publish results

`python3 -m evals.run && python3 scripts/bench.py && python3 -m evals.elog_eval && python3 -m evals.charts &&
python3 -m evals.console_data && python3 -m evals.readme`, then commit `reports/`, `docs/charts/`,
`web/public/data/` and `README.md` together.

## Run the held-out campaign

Only once, from a clean commit: `python3 -m evals.run --heldout`, then `python3 -m evals.readme`, and write what
happened in `docs/heldout.md`.
