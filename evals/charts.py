"""Charts for the README, generated from reports/ and a showcase run. python3 -m evals.charts"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from evals import showcase  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "charts"
INK, MUTED, GRID = "#1d2433", "#6b7385", "#e4e7ee"
PLATFORM, STATUS, OTHER, ALERT = "#1f6f8b", "#b4552d", "#9aa3b5", "#c4302b"

plt.rcParams.update(
    {
        "font.family": ["Inter", "DejaVu Sans"],
        "font.size": 10,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def designs_chart() -> None:
    rep = json.loads((ROOT / "reports" / "dev.json").read_text())
    names = sorted(rep["designs"], key=lambda n: rep["designs"][n]["summary"]["good_shots_per_day"]["mean"])
    means = [rep["designs"][n]["summary"]["good_shots_per_day"]["mean"] for n in names]
    sds = [rep["designs"][n]["summary"]["good_shots_per_day"]["sd"] or 0 for n in names]
    colors = [PLATFORM if n == "platform" else STATUS if n == "manual_ops" else OTHER for n in names]
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=150)
    y = np.arange(len(names))
    ax.barh(y, means, xerr=sds, color=colors, error_kw={"ecolor": MUTED, "elinewidth": 1, "capsize": 2})
    ax.set_yticks(y, [n.replace("_", " ") for n in names])
    for yi, m, sd in zip(y, means, sds, strict=True):
        ax.text(m + sd + 2, yi, f"{m:.0f}", va="center", color=INK, fontsize=9)
    ax.set_xlabel("Good shots per 8-hour shift (in spec, undamaged optic); mean ± sd over 3 beamlines")
    ax.grid(axis="x", color=GRID)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "designs.png")
    plt.close(fig)


def shift_chart() -> None:
    fig, axes = plt.subplots(2, 1, figsize=(8, 5.6), dpi=150, sharex=True)
    for ax, design, color, title in (
        (axes[0], "manual_ops", STATUS, "Status quo"),
        (axes[1], "platform", PLATFORM, "Platform"),
    ):
        r = showcase.run(design)
        pulses = {p.pulse_id: p for p in r.world.pulses}
        shots = [s for s in r.ops.shots if s.day == showcase.SHIFT and s.purpose == "experiment"]
        t = [s.t_s / 3600 for s in shots]
        ff = [float(np.hypot(*pulses[s.pulse_id].ff_urad)) for s in shots]
        dmg = [pulses[s.pulse_id].damaged for s in shots]
        ax.scatter(t, ff, s=8, color=color, label="fired shot")
        ax.scatter(
            [ti for ti, d in zip(t, dmg, strict=True) if d],
            [f for f, d in zip(ff, dmg, strict=True) if d],
            s=14,
            facecolors="none",
            edgecolors=ALERT,
            label="damaging shot",
        )
        holds = [(day, ts) for (_, day, ts, _, d) in r.ops.decisions if day == showcase.SHIFT and not d.permit]
        for _, ts in holds:
            ax.axvline(ts / 3600, color=ALERT, lw=0.8, alpha=0.6)
        ax.axhline(5.0, color=MUTED, lw=1, ls="--")
        ax.text(0.02, 5.4, "tolerance 5 µrad", color=MUTED, fontsize=8)
        ax.set_ylabel("true pointing error, µrad")
        ax.set_ylim(0, max(16, min(40, max(ff) * 1.1)))
        ax.set_title(f"{title}: shift {showcase.SHIFT} of dev beamline {showcase.SEED}", loc="left", color=INK, fontsize=10)
        ax.grid(axis="y", color=GRID)
        ax.legend(loc="upper right", frameon=False, fontsize=8)
    hs = [e for e in showcase.run("platform").world.events if e.kind == "hotspot" and e.day == showcase.SHIFT]
    for e in hs:
        for ax in axes:
            ax.annotate("hot spot appears", (e.t_s / 3600, ax.get_ylim()[1] * 0.92), color=ALERT, fontsize=8)
    axes[1].set_xlabel("hours into the shift (red lines: shots held by the interlocks)")
    fig.tight_layout()
    fig.savefig(OUT / "shift.png")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    designs_chart()
    shift_chart()
    print("wrote docs/charts/designs.png, docs/charts/shift.png")


if __name__ == "__main__":
    main()
