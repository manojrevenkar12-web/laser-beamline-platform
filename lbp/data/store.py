"""Experimental and operational data: shot records in SQLite, camera frames in HDF5.

A shot is written once. Writing the same record again is a no-op; writing a different record under the same
shot id is refused, so a replayed or retried pipeline cannot silently change history. Every shot carries the
ids of the calibrations it was measured with (camera dark and hot-pixel map, interaction matrix, energy
factor), so any number can be traced to the calibration behind it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS shots (
  shot_id TEXT PRIMARY KEY, pulse_id INTEGER, day INTEGER, t_s REAL, purpose TEXT,
  pump REAL, energy_target_j REAL, energy_raw_j REAL, energy_reported_j REAL,
  nf_x_mm REAL, nf_y_mm REAL, ff_x_urad REAL, ff_y_urad REAL, nf_d4_mm REAL,
  peak_fraction REAL, fluence_est_j_cm2 REAL, predicted_fluence_j_cm2 REAL, saturated INTEGER,
  pre_error TEXT, calibrations TEXT, decision_id TEXT, digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY, day INTEGER, t_s REAL, permit INTEGER, reasons TEXT, warnings TEXT,
  predicted_fluence_j_cm2 REAL, limit_j_cm2 REAL, action TEXT
);
CREATE TABLE IF NOT EXISTS calibrations (
  cal_id TEXT PRIMARY KEY, kind TEXT, day INTEGER, t_s REAL, summary TEXT
);
CREATE TABLE IF NOT EXISTS alignments (
  align_id INTEGER PRIMARY KEY AUTOINCREMENT, day INTEGER, t_s REAL, summary TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
  alert_id TEXT PRIMARY KEY, day INTEGER, t_s REAL, severity TEXT, kind TEXT, message TEXT
);
CREATE INDEX IF NOT EXISTS shots_day ON shots(day);
"""

SHOT_FIELDS = (
    "shot_id",
    "pulse_id",
    "day",
    "t_s",
    "purpose",
    "pump",
    "energy_target_j",
    "energy_raw_j",
    "energy_reported_j",
    "nf_x_mm",
    "nf_y_mm",
    "ff_x_urad",
    "ff_y_urad",
    "nf_d4_mm",
    "peak_fraction",
    "fluence_est_j_cm2",
    "predicted_fluence_j_cm2",
    "saturated",
    "pre_error",
    "calibrations",
    "decision_id",
)


class Conflict(Exception):
    """A different record already exists under this id."""


def digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


class Store:
    def __init__(self, root: str | Path | None = None, frames: bool = True, compression: str = "gzip", level: int = 4):
        self.root = Path(root) if root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.root / "shots.sqlite", check_same_thread=False)
        else:
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.frames = bool(frames and self.root)
        self.compression, self.level = compression, level

    @classmethod
    def from_config(cls, cfg: dict, root: str | Path | None = None, frames: bool | None = None) -> Store:
        d = cfg["data"]
        return cls(
            root if root is not None else d["root"],
            frames=d["frames"] if frames is None else frames,
            compression=d["compression"],
            level=int(d["compression_level"]),
        )

    # ------------------------------------------------------------------ writes

    def put_shot(self, rec: dict) -> bool:
        """Insert a shot once. Returns True if written, False if the identical record was already there."""
        row = {k: rec.get(k) for k in SHOT_FIELDS}
        for k in ("pre_error", "calibrations"):
            if not isinstance(row[k], str):
                row[k] = json.dumps(row[k], sort_keys=True)
        d = digest(row)
        existing = self.db.execute("SELECT digest FROM shots WHERE shot_id = ?", (row["shot_id"],)).fetchone()
        if existing:
            if existing[0] == d:
                return False
            raise Conflict(f"shot {row['shot_id']} already stored with different content")
        cols = ", ".join([*SHOT_FIELDS, "digest"])
        marks = ", ".join("?" * (len(SHOT_FIELDS) + 1))
        self.db.execute(f"INSERT INTO shots ({cols}) VALUES ({marks})", [row[k] for k in SHOT_FIELDS] + [d])
        self.db.commit()
        return True

    def put_decision(self, decision_id: str, day: int, t_s: float, d: dict) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision_id,
                day,
                t_s,
                int(d["permit"]),
                json.dumps(d["reasons"]),
                json.dumps(d["warnings"]),
                d["predicted_fluence_j_cm2"],
                d["limit_j_cm2"],
                d["action"],
            ),
        )
        self.db.commit()

    def put_calibration(self, kind: str, day: int, t_s: float, summary: dict) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO calibrations VALUES (?, ?, ?, ?, ?)", (summary["cal_id"], kind, day, t_s, json.dumps(summary))
        )
        self.db.commit()

    def put_alignment(self, day: int, t_s: float, summary: dict) -> None:
        self.db.execute("INSERT INTO alignments (day, t_s, summary) VALUES (?, ?, ?)", (day, t_s, json.dumps(summary)))
        self.db.commit()

    def put_alert(self, alert_id: str, day: int, t_s: float, severity: str, kind: str, message: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO alerts VALUES (?, ?, ?, ?, ?, ?)", (alert_id, day, t_s, severity, kind, message))
        self.db.commit()

    def put_frames(self, shot_id: str, day: int, frames: dict[str, np.ndarray], attrs: dict[str, dict]) -> bool:
        if not self.frames:
            return False
        import h5py

        assert self.root is not None
        path = self.root / "frames" / f"day-{day:03d}.h5"
        path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(path, "a") as h5:
            grp_name = f"shots/{shot_id}"
            if grp_name in h5:
                return False
            grp = h5.create_group(grp_name)
            for cam, image in frames.items():
                ds = grp.create_dataset(cam, data=image, chunks=image.shape, compression=self.compression, compression_opts=self.level)
                for k, v in attrs.get(cam, {}).items():
                    ds.attrs[k] = v
        return True

    # ------------------------------------------------------------------ reads

    def shots(self, day: int | None = None, purpose: str | None = None, limit: int = 100000) -> list[dict]:
        q, args = "SELECT * FROM shots WHERE 1=1", []
        if day is not None:
            q += " AND day = ?"
            args.append(day)
        if purpose is not None:
            q += " AND purpose = ?"
            args.append(purpose)
        q += " ORDER BY day, t_s LIMIT ?"
        args.append(limit)
        cur = self.db.execute(q, args)
        cols = [c[0] for c in cur.description]
        out = []
        for r in cur.fetchall():
            rec = dict(zip(cols, r, strict=True))
            rec["pre_error"] = json.loads(rec["pre_error"]) if rec["pre_error"] else None
            rec["calibrations"] = json.loads(rec["calibrations"]) if rec["calibrations"] else {}
            out.append(rec)
        return out

    def shot(self, shot_id: str) -> dict | None:
        rows = [r for r in self.shots() if r["shot_id"] == shot_id]
        return rows[0] if rows else None

    def table(self, name: str) -> list[dict]:
        if name not in ("decisions", "calibrations", "alignments", "alerts"):
            raise ValueError(name)
        cur = self.db.execute(f"SELECT * FROM {name}")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def frame(self, day: int, shot_id: str, camera: str) -> np.ndarray | None:
        if not self.frames:
            return None
        import h5py

        assert self.root is not None
        path = self.root / "frames" / f"day-{day:03d}.h5"
        if not path.exists():
            return None
        with h5py.File(path, "r") as h5:
            key = f"shots/{shot_id}/{camera}"
            return np.array(h5[key]) if key in h5 else None
