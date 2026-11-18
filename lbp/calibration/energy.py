"""Energy-meter cross-calibration against a reference meter with a valid certificate.

Paired readings on full shots give the factor that maps the pick-off meter onto the reference. The expanded
uncertainty combines the scatter of the ratios (type A) with the reference's certificate (type B, k = 2). The
procedure refuses to start with a reference past its due date, and a factor whose uncertainty exceeds the
limit is recorded but not applied.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

_ids = itertools.count(1)


@dataclass
class EnergyCal:
    day: int
    factor: float
    u_k2: float  # expanded relative uncertainty
    n: int
    applied: bool
    reason: str
    previous: float
    cal_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.cal_id:
            self.cal_id = f"em-cal-{next(_ids):04d}"

    @property
    def change(self) -> float:
        return self.factor / self.previous - 1.0

    def summary(self) -> dict:
        return {
            "cal_id": self.cal_id,
            "day": self.day,
            "factor": round(self.factor, 6),
            "u_k2": round(self.u_k2, 6),
            "n": self.n,
            "applied": self.applied,
            "reason": self.reason,
            "change": round(self.change, 6),
        }


def evaluate(day: int, raw: list[float], reference: list[float], ref_u_k2: float, previous: float, max_u_k2: float) -> EnergyCal:
    pairs = [(r, q) for r, q in zip(raw, reference, strict=True) if r and q and r > 0 and q > 0]
    n = len(pairs)
    if n < 5:
        return EnergyCal(day, previous, math.inf, n, False, "too few paired readings", previous)
    ratios = [q / r for r, q in pairs]
    mean = sum(ratios) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in ratios) / (n - 1))
    u_a = sd / math.sqrt(n) / mean
    u_b = ref_u_k2 / 2.0
    u_k2 = 2.0 * math.sqrt(u_a**2 + u_b**2)
    if u_k2 > max_u_k2:
        return EnergyCal(day, mean, u_k2, n, False, f"uncertainty {u_k2:.4f} above {max_u_k2:.4f}", previous)
    return EnergyCal(day, mean, u_k2, n, True, "applied", previous)
