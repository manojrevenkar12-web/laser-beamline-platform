"""Platform settings: config/platform.toml and the designs in config/designs.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


def load(name: str = "platform.toml") -> dict:
    with open(CONFIG / name, "rb") as fh:
        return tomllib.load(fh)


@dataclass(frozen=True)
class Design:
    name: str
    description: str
    analysis: str
    background: bool
    hot_pixel_mask: bool
    iso_aperture: bool
    auto_exposure: bool
    alignment: str
    matrix: str
    backlash_compensation: bool
    matrix_refresh: bool
    realign: str
    preshot_pulse: bool
    fluence_interlock: bool
    energy_cross_cal: bool
    routine_inspection: bool

    def __post_init__(self) -> None:
        if self.analysis not in ("iso", "naive"):
            raise ValueError(f"{self.name}: analysis {self.analysis}")
        if self.alignment not in ("auto", "manual"):
            raise ValueError(f"{self.name}: alignment {self.alignment}")
        if self.matrix not in ("measured", "nominal"):
            raise ValueError(f"{self.name}: matrix {self.matrix}")
        if self.realign not in ("condition", "schedule", "operator"):
            raise ValueError(f"{self.name}: realign {self.realign}")


def designs() -> dict[str, Design]:
    raw = load("designs.toml")
    names = {f.name for f in fields(Design)}
    out: dict[str, Design] = {}
    for name, spec in raw.items():
        merged = dict(raw[spec["base"]]) if "base" in spec else {}
        merged.update({k: v for k, v in spec.items() if k != "base"})
        merged["name"] = name
        out[name] = Design(**{k: merged[k] for k in names})
    return out


def design(name: str) -> Design:
    return designs()[name]
