"""Shift handover for the electronic logbook: a model may draft it, code checks every number before it posts.

`facts` collects what the data store can prove about a shift. `draft` writes the note: with ANTHROPIC_API_KEY
set it asks a model to write it from the facts only; otherwise a template writes it. Either way `check` reads
every number and shot id in the draft and refuses the note if one is not backed by the facts, so a fluent
but wrong sentence never reaches the logbook.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from lbp.data.store import Store

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
SHOT_ID = re.compile(r"\bS\d{3}-\d{5}\b")


def facts(store: Store, day: int) -> dict:
    shots = store.shots(day=day)
    exp = [s for s in shots if s["purpose"] == "experiment"]
    decisions = [d for d in store.table("decisions") if d["day"] == day]
    held = [d for d in decisions if not d["permit"]]
    reasons = Counter(r.split(" ")[0] + " " + r.split(" ")[1] if " " in r else r for d in held for r in json.loads(d["reasons"]))
    alerts = [a for a in store.table("alerts") if a["day"] == day and a["kind"] != "hot-pixels"]
    aligns = [json.loads(a["summary"]) for a in store.table("alignments") if a["day"] == day]
    energies = [s["energy_reported_j"] for s in exp if s["energy_reported_j"] is not None]
    cals = [json.loads(c["summary"]) for c in store.table("calibrations") if c["day"] == day and c["kind"] == "energy"]
    out = {
        "day": day,
        "shots_fired": len(exp),
        "calibration_shots": len(shots) - len(exp),
        "shots_held": len(held),
        "held_reasons": dict(reasons.most_common(3)),
        "alignments": len(aligns),
        "alignment_minutes": round(sum(a["seconds"] for a in aligns) / 60.0, 1),
        "mean_energy_j": round(sum(energies) / len(energies), 2) if energies else None,
        "alerts": [{"kind": a["kind"], "message": a["message"]} for a in alerts],
        "energy_calibrations": [{"cal_id": c["cal_id"], "applied": c["applied"], "u_k2_percent": round(100 * c["u_k2"], 2)} for c in cals],
        "first_shot": exp[0]["shot_id"] if exp else None,
        "last_shot": exp[-1]["shot_id"] if exp else None,
    }
    return out


def template_draft(f: dict) -> str:
    lines = [f"Shift handover, day {f['day']}."]
    lines.append(f"{f['shots_fired']} experiment shots fired, {f['shots_held']} held by the interlocks.")
    if f["first_shot"]:
        lines.append(f"Shots {f['first_shot']} to {f['last_shot']}; mean reported energy {f['mean_energy_j']} J.")
    lines.append(f"{f['alignments']} alignments took {f['alignment_minutes']} minutes.")
    for c in f["energy_calibrations"]:
        state = "applied" if c["applied"] else "not applied"
        lines.append(f"Energy meter cross-calibration {c['cal_id']} {state}, expanded uncertainty {c['u_k2_percent']} %.")
    for a in f["alerts"]:
        lines.append(f"Alert ({a['kind']}): {a['message']}.")
    return "\n".join(lines)


def model_draft(f: dict, model: str = "claude-haiku-4-5") -> str:  # pragma: no cover - needs a key
    import anthropic

    client = anthropic.Anthropic()
    prompt = (
        "Write a short shift handover note for a laser lab's electronic logbook. Use only the facts in the JSON. "
        "Every number and shot id you write must appear in the JSON. Plain sentences, no headings.\n\n" + json.dumps(f, indent=1)
    )
    msg = client.messages.create(model=model, max_tokens=400, messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def draft(f: dict) -> tuple[str, str]:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return model_draft(f), "model"
    return template_draft(f), "template"


def _numbers(obj: object) -> set[float]:
    found: set[float] = set()
    if isinstance(obj, bool) or obj is None:
        return found
    if isinstance(obj, (int, float)):
        found.add(round(float(obj), 2))
    elif isinstance(obj, str):
        for m in NUMBER.findall(obj):
            found.add(round(float(m), 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= _numbers(v)
        for k in obj:
            found |= _numbers(k)
    elif isinstance(obj, list):
        for v in obj:
            found |= _numbers(v)
    return found


def _ids(obj: object) -> set[str]:
    return set(SHOT_ID.findall(json.dumps(obj)))


@dataclass
class Check:
    ok: bool
    problems: list[str] = field(default_factory=list)


def check(text: str, f: dict) -> Check:
    """Every number in the draft must be a number in the facts; every shot id must be one of the shift's."""
    allowed = _numbers(f)
    ids = _ids(f)
    problems = []
    stripped = SHOT_ID.sub(lambda m: "" if m.group(0) in ids else m.group(0), text)
    for sid in SHOT_ID.findall(stripped):
        problems.append(f"unknown shot id {sid}")
    stripped = SHOT_ID.sub("", stripped)
    for m in NUMBER.findall(stripped):
        if round(float(m), 2) not in allowed:
            problems.append(f"number {m} is not in the shift's facts")
    return Check(ok=not problems, problems=problems)
