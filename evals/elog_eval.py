"""How well the handover checker stops wrong numbers: clean drafts and drafts with planted errors.

The checker is what stands between a model's draft and the logbook, so it is what this measures. Drafts come
from the template (the build environment has no model key); the planted errors are the ones a fluent model
makes: a changed count, a rounded value moved, an invented shot id, a number from another day.

    python3 -m evals.elog_eval      -> reports/elog.json
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from evals.operate import operate
from lbp.elog import handover

ROOT = Path(__file__).resolve().parent.parent


def plant(text: str, f: dict, other: dict, rng: random.Random) -> tuple[str, str]:
    kind = rng.choice(["count", "decimal", "shot_id", "other_day"])
    nums = [m for m in handover.NUMBER.finditer(text) if not handover.SHOT_ID.search(text[max(0, m.start() - 5) : m.end() + 6])]
    if kind == "count" and nums:
        m = rng.choice(nums)
        v = m.group(0)
        new = str(int(float(v)) + rng.choice([1, 2, 5, 10])) if "." not in v else str(round(float(v) + 1, 1))
        return text[: m.start()] + new + text[m.end() :], kind
    if kind == "decimal":
        decs = [m for m in nums if "." in m.group(0)]
        if decs:
            m = rng.choice(decs)
            new = f"{float(m.group(0)) * 1.07:.2f}"
            return text[: m.start()] + new + text[m.end() :], kind
    if kind == "shot_id":
        return text + f"\nShot S{f['day']:03d}-{rng.randint(90000, 99999)} showed the best pointing.", kind
    candidates = sorted(handover._numbers(other) - handover._numbers(f))
    candidates = [c for c in candidates if c > 1]
    if candidates:
        return text + f"\nThe previous shift fired {int(rng.choice(candidates))} shots.", "other_day"
    return text + "\nPeak fluence stayed below 2.37 J/cm2.", "invented"


def main() -> None:
    rng = random.Random(7)
    rows, clean_ok, planted_caught, planted = [], 0, 0, 0
    for seed in (11, 12):
        run = operate("platform", seed, days=4)
        facts = [handover.facts(run.ops.store, d) for d in range(4)]
        for d in range(4):
            text = handover.template_draft(facts[d])
            clean_ok += handover.check(text, facts[d]).ok
            for _ in range(25):
                bad, kind = plant(text, facts[d], facts[(d + 1) % 4], rng)
                if bad == text:
                    continue
                planted += 1
                caught = not handover.check(bad, facts[d]).ok
                planted_caught += caught
                rows.append({"seed": seed, "day": d, "kind": kind, "caught": caught})
    by_kind: dict[str, list[bool]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r["caught"])
    out = {
        "clean_drafts": 8,
        "clean_passed": clean_ok,
        "planted": planted,
        "planted_caught": planted_caught,
        "by_kind": {k: {"n": len(v), "caught": sum(v)} for k, v in sorted(by_kind.items())},
        "note": "drafts written by the template; with ANTHROPIC_API_KEY set, lbp.elog.handover.draft asks a model instead",
    }
    (ROOT / "reports" / "elog.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
