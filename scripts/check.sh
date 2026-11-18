#!/usr/bin/env bash
# Fast feedback: build the C++ engine, run its tests, lint, run the Python tests, check the README is current.
set -euo pipefail
cd "$(dirname "$0")/.."
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -Wno-dev > /dev/null
cmake --build build -j "$(nproc)" > /dev/null
./build/beamcore_tests > /dev/null && echo "beamcore tests: ok"
python3 -m ruff check lbp world evals tests scripts
python3 -m ruff format --check lbp world evals tests scripts
python3 -m pytest -q
python3 -m evals.readme --check
