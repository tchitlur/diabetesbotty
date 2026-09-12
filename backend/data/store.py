"""Patient data store: load a patient directory (demo or cohort member) into
one object the rest of the backend uses."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
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


def load_patient(patient_id: str = "demo") -> PatientData:
    d = patient_dir(patient_id)
    meta = json.loads((d / "patient.json").read_text(encoding="utf-8"))
    events = events_from_dicts(json.loads((d / "events.json").read_text(encoding="utf-8")))
    et_path = d / "events_true.json"
    events_true = events_from_dicts(json.loads(et_path.read_text(encoding="utf-8"))) if et_path.exists() else events
    cgm = ingest_csv(d / "cgm.csv")
    daily = pd.read_csv(d / "daily.csv", parse_dates=["date"])
    truth = pd.read_csv(d / "truth_glucose.csv", parse_dates=["time"]) if (d / "truth_glucose.csv").exists() else None
    fit = json.loads((d / "fit.json").read_text(encoding="utf-8")) if (d / "fit.json").exists() else None
    return PatientData(patient_id=meta["patient_id"], path=d, meta=meta, events=events, events_true=events_true,
                       cgm=cgm, daily=daily, truth=truth, fit=fit)


def list_cohort() -> List[str]:
    if not COHORT_DIR.exists():
        return []
    return sorted(p.name for p in COHORT_DIR.iterdir() if (p / "patient.json").exists())
