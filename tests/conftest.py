from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def cfg() -> dict:
    from lbp import config

    return config.load()


@pytest.fixture(scope="session")
def wcfg() -> dict:
    with open(ROOT / "config" / "world.toml", "rb") as fh:
        return tomllib.load(fh)


@pytest.fixture
def line(wcfg):
    from world.beamline import Beamline

    b = Beamline(wcfg, 11)
    b.start_day(0)
    return b


@pytest.fixture
def ops_factory(cfg, wcfg):
    """Build platform operations on a fresh beamline (loopback transports)."""

    def make(design: str = "platform", seed: int = 11, world: dict | None = None, store=None):
        from evals.operate import connect
        from lbp import config
        from lbp.control.operations import Operations
        from world.beamline import Beamline
        from world.emulators import SimClock

        line = Beamline(world or wcfg, seed)
        line.start_day(0)
        ops = Operations(cfg, config.design(design), connect(line, cfg), SimClock(line), store=store)
        return line, ops

    return make


@pytest.fixture(scope="session")
def platform_day():
    """One full simulated shift of the platform, shared by the tests that only read its results."""
    from evals.operate import operate

    return operate("platform", 11, days=1)
