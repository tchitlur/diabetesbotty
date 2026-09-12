"""Patient data store: load a patient directory (demo or cohort member) into
one object the rest of the backend uses."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backend.config import DEMO_PATIENT_DIR, COHORT_DIR
from backend.schema.events import Event, events_from_dicts
from backend.adapters.csv_ingest import ingest_csv, GlucoseSeries


@dataclass
class PatientData:
    patient_id: str
    path: Path
    meta: Dict[str, Any]
    events: List[Event]                    # logged events (what the twin sees)
    events_true: List[Event]               # ground truth (validation only)
    cgm: GlucoseSeries
    daily: pd.DataFrame
    truth: Optional[pd.DataFrame] = None   # noise-free glucose (validation only)
    fit: Optional[Dict[str, Any]] = None

    @property
    def true_params(self) -> Dict[str, Any]:
        return self.meta["true_params"]

    @property
    def now(self) -> datetime:
        return self.cgm.times[-1].to_pydatetime()

    def events_between(self, a: datetime, b: datetime, true: bool = False) -> List[Event]:
        src = self.events_true if true else self.events
        return [e for e in src if a <= e.start < b]

    def glucose_frame(self) -> pd.DataFrame:
        return self.cgm.to_frame()


def patient_dir(patient_id: str) -> Path:
    if patient_id in ("demo", "demo_patient"):
        return DEMO_PATIENT_DIR
    return COHORT_DIR / patient_id


def _shift_event(e: Event, shift: timedelta) -> Event:
    return e.copy(start_time=(e.start + shift).isoformat(timespec="minutes"))


def load_patient(patient_id: str = "demo", until: Optional[datetime] = None, shift: Optional[timedelta] = None) -> PatientData:
    """Load a patient. `until` truncates CGM and events to that moment (the twin must never
    see the future). `shift` moves every timestamp (events, sensor, daily rows, truth) by a
    fixed offset: the live app maps the synthetic anchor onto the real wall clock this way;
    the files on disk keep their synthetic dates. `until` is in shifted time."""
    d = patient_dir(patient_id)
    shift = shift or timedelta(0)
    until_raw = until - shift if until is not None else None
    meta = json.loads((d / "patient.json").read_text(encoding="utf-8"))
    events = events_from_dicts(json.loads((d / "events.json").read_text(encoding="utf-8")))
    et_path = d / "events_true.json"
    events_true = events_from_dicts(json.loads(et_path.read_text(encoding="utf-8"))) if et_path.exists() else events
    if until_raw is not None:
        events = [e for e in events if e.start <= until_raw]
        events_true = [e for e in events_true if e.start <= until_raw]
    cgm = ingest_csv(d / "cgm.csv", now=until_raw, until=until_raw)
    daily = pd.read_csv(d / "daily.csv", parse_dates=["date"])
    truth = pd.read_csv(d / "truth_glucose.csv", parse_dates=["time"]) if (d / "truth_glucose.csv").exists() else None
    fit = json.loads((d / "fit.json").read_text(encoding="utf-8")) if (d / "fit.json").exists() else None
    if shift:
        events = [_shift_event(e, shift) for e in events]
        events_true = [_shift_event(e, shift) for e in events_true]
        cgm.times = cgm.times + shift
        for g in cgm.gaps:
            for k in ("start", "end"):
                if isinstance(g.get(k), (datetime, pd.Timestamp)):
                    g[k] = g[k] + shift
        daily["date"] = daily["date"] + shift
        if truth is not None:
            truth["time"] = truth["time"] + shift
    return PatientData(patient_id=meta["patient_id"], path=d, meta=meta, events=events, events_true=events_true,
                       cgm=cgm, daily=daily, truth=truth, fit=fit)


def list_cohort() -> List[str]:
    if not COHORT_DIR.exists():
        return []
    return sorted(p.name for p in COHORT_DIR.iterdir() if (p / "patient.json").exists())
