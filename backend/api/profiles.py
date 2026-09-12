"""Profiles: who is using the app. Each profile is a JSON file under
backend/data/profiles/ and is bound to one synthetic cohort patient whose
data the twin runs on. No passwords (demo). Nothing is stored in the browser."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.config import DATA_DIR, DEMO_PATIENT_DIR, COHORT_DIR

PROFILES_DIR = DATA_DIR / "profiles"
ACTIVE_PATH = PROFILES_DIR / "active.json"


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    age: int = Field(ge=10, le=100)
    sex: str = Field(pattern="^(F|M|other)$")
    weight_kg: float = Field(gt=25, lt=250)
    height_cm: float = Field(gt=100, lt=230)
    carb_ratio_g_per_u: float = Field(gt=2, lt=60)          # grams of carbs covered by 1 unit
    correction_factor_mgdl_per_u: float = Field(gt=5, lt=200)  # mg/dL lowered by 1 unit
    target_low: float = Field(ge=60, le=120)
    target_high: float = Field(ge=120, le=250)


class Profile(ProfileIn):
    id: str
    patient_id: str
    initial: str
    created_at: str
    fitted: bool = False
    fit_seconds: float = 0.0


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "profile"
    return s[:24]


def _path(pid: str) -> Path:
    return PROFILES_DIR / f"{pid}.json"


def list_profiles() -> List[Profile]:
    ensure_seed()
    out = []
    for p in sorted(PROFILES_DIR.glob("*.json")):
        if p.name == "active.json":
            continue
        try:
            out.append(Profile(**json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    out.sort(key=lambda x: x.created_at)
    return out


def get_profile(pid: str) -> Optional[Profile]:
    p = _path(pid)
    if not p.exists():
        return None
    return Profile(**json.loads(p.read_text(encoding="utf-8")))


def save_profile(prof: Profile) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    _path(prof.id).write_text(json.dumps(prof.model_dump(), indent=2), encoding="utf-8")


def active_id() -> str:
    ensure_seed()
    if ACTIVE_PATH.exists():
        try:
            pid = json.loads(ACTIVE_PATH.read_text(encoding="utf-8")).get("id", "demo")
            if _path(pid).exists():
                return pid
        except Exception:
            pass
    return "demo"


def set_active(pid: str) -> Profile:
    prof = get_profile(pid)
    if prof is None:
        raise KeyError(pid)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_PATH.write_text(json.dumps({"id": pid}), encoding="utf-8")
    return prof


def ensure_seed() -> None:
    """The demo profile (bound to the committed demo patient) always exists."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    if _path("demo").exists():
        return
    meta = json.loads((DEMO_PATIENT_DIR / "patient.json").read_text(encoding="utf-8"))
    # the demo person's carb ratio is the one the twin titrates on its own fitted physiology
    try:
        from backend.data.store import load_patient
        from backend.inference.fitter import fitted_params
        from backend.engine import fast
        cr = float(fast.calibrate_carb_ratio(fitted_params(load_patient("demo"))))
    except Exception:
        cr = float(meta["true_params"].get("carb_ratio_g_per_u", 12.0))
    prof = Profile(id="demo", patient_id="demo", initial="A", name="Alex", age=34, sex=meta.get("sex", "M"),
                   weight_kg=round(float(meta["body_weight_kg"]), 1), height_cm=180.0,
                   carb_ratio_g_per_u=round(cr, 1),
                   correction_factor_mgdl_per_u=50.0, target_low=70.0, target_high=180.0,
                   created_at="2025-08-01T00:00", fitted=True)
    save_profile(prof)


def _cohort_ids() -> List[str]:
    if not COHORT_DIR.exists():
        return []
    return sorted(p.name for p in COHORT_DIR.iterdir() if (p / "patient.json").exists() and p.name != "p00")


def assign_patient(body: ProfileIn) -> str:
    """Pick the cohort patient closest to the new profile (same sex first, then body weight)
    that no other profile already uses. Falls back to the demo patient if the cohort is absent."""
    used = {p.patient_id for p in list_profiles()}
    best, best_d = None, 1e9
    for cid in _cohort_ids():
        if cid in used:
            continue
        meta = json.loads((COHORT_DIR / cid / "patient.json").read_text(encoding="utf-8"))
        d = abs(float(meta["body_weight_kg"]) - body.weight_kg) + (0 if meta.get("sex") == body.sex else 15.0)
        if d < best_d:
            best, best_d = cid, d
    return best or "demo"


def create_profile(body: ProfileIn, fit: bool = True) -> Profile:
    pid = _slug(body.name)
    base, k = pid, 2
    while _path(pid).exists():
        pid, k = f"{base}-{k}", k + 1
    patient = assign_patient(body)
    prof = Profile(id=pid, patient_id=patient, initial=body.name.strip()[0].upper(), created_at=time.strftime("%Y-%m-%dT%H:%M"),
                   **body.model_dump())
    t0 = time.time()
    if fit and patient != "demo":
        from backend.data.store import patient_dir
        from backend.inference.fitter import fit_patient
        if not (patient_dir(patient) / "fit.json").exists():
            fit_patient(patient, verbose=False)
    prof.fitted = True
    prof.fit_seconds = round(time.time() - t0, 1)
    save_profile(prof)
    return prof


def delete_profile(pid: str) -> bool:
    if pid == "demo":
        return False
    p = _path(pid)
    if p.exists():
        p.unlink()
        if active_id() == pid:
            set_active("demo")
        return True
    return False
