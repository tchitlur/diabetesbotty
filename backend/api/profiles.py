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
    # who they are, in one line each (the login list and the switcher show these)
    avatar: str = ""            # one emoji
    occupation: str = ""
    habit: str = ""             # "runs before work"
    t1d_years: int = 0
    sensor_days: int = 90
    signature: str = ""         # the one question that shows what is special about this person
    random: bool = False


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
    """The five demo people always exist (Alex is bound to the committed demo patient and is
    already fitted; the others are fitted on first selection or by the startup prefit)."""
    from backend.api.personas import PERSONAS
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    for spec in PERSONAS:
        path = _path(spec["id"])
        if path.exists():
            cur = json.loads(path.read_text(encoding="utf-8"))
            if cur.get("occupation") == spec["occupation"] and cur.get("avatar") == spec["avatar"] and cur.get("patient_id") == spec["patient_id"] and cur.get("carb_ratio_g_per_u") == spec["carb_ratio_g_per_u"]:
                continue
            fitted = bool(cur.get("fitted")) and cur.get("patient_id") == spec["patient_id"]
        else:
            fitted = spec["patient_id"] == "demo"
        if spec["patient_id"] != "demo":
            from backend.data.store import patient_dir
            fitted = fitted or (patient_dir(spec["patient_id"]) / "fit.json").exists()
        prof = Profile(initial=spec["name"][0].upper(), fitted=fitted, **spec)
        save_profile(prof)
    # earlier single-seed installs left a profile file per created person; they stay


def fit_persona(pid: str) -> Profile:
    """Fit the twin of an unfitted person (about 10 s) and mark the profile fitted."""
    prof = get_profile(pid)
    if prof is None:
        raise KeyError(pid)
    if prof.fitted:
        return prof
    from backend.data.store import patient_dir
    from backend.inference.fitter import fit_patient
    t0 = time.time()
    if prof.patient_id != "demo" and not (patient_dir(prof.patient_id) / "fit.json").exists():
        fit_patient(prof.patient_id, verbose=False)
    apply_demo_tuning(pid, prof.patient_id)
    prof.fitted = True
    prof.fit_seconds = round(time.time() - t0, 1)
    save_profile(prof)
    return prof


def apply_demo_tuning(pid: str, patient_id: str) -> None:
    """The /compare demo tunes two people's fitted parameters (backend/data/compare_personas.json,
    within the plausible ranges). The same values go into their fit files so the app's dashboards
    and the demo page run one model, on every machine the cohort is regenerated on."""
    from backend.data.store import patient_dir
    path = DATA_DIR / "compare_personas.json"
    fit_path = patient_dir(patient_id) / "fit.json"
    if not path.exists() or not fit_path.exists():
        return
    over = json.loads(path.read_text(encoding="utf-8")).get(pid)
    if not over:
        return
    fit = json.loads(fit_path.read_text(encoding="utf-8"))
    changed = False
    for k, v in over.items():
        if k == "_std_scale":
            for kk, row in fit.get("params", {}).items():
                if row.get("std_raw") is None:
                    row["std_raw"] = row.get("std", 0.0)
                if row.get("std") != float(row["std_raw"]) * float(v):
                    row["std"] = float(row["std_raw"]) * float(v)
                    changed = True
            continue
        if k in fit.get("params", {}) and fit["params"][k].get("mean") != float(v):
            fit["params"][k]["mean"] = float(v)
            changed = True
    if changed:
        fit["tuned_for_demo"] = over
        fit_path.write_text(json.dumps(fit, indent=1), encoding="utf-8")


def create_random(seed: Optional[int] = None) -> Profile:
    """"Random new person": a plausible new person bound to an unused cohort patient, fitted now."""
    import random as _random
    from backend.api.personas import random_body
    rng = _random.Random(seed if seed is not None else time.time_ns())
    used = [p.name for p in list_profiles()]
    body = random_body(rng, used)
    fields = {k: v for k, v in body.items() if k in ProfileIn.model_fields}
    extra = {k: v for k, v in body.items() if k not in ProfileIn.model_fields}
    prof = create_profile(ProfileIn(**fields), fit=True, extra={**extra, "random": True})
    return prof


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


def create_profile(body: ProfileIn, fit: bool = True, extra: Optional[Dict[str, Any]] = None) -> Profile:
    pid = _slug(body.name)
    base, k = pid, 2
    while _path(pid).exists():
        pid, k = f"{base}-{k}", k + 1
    patient = assign_patient(body)
    prof = Profile(id=pid, patient_id=patient, initial=body.name.strip()[0].upper(), created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                   **body.model_dump(), **(extra or {}))
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
    from backend.api.personas import PERSONA_IDS
    if pid in PERSONA_IDS:
        return False
    p = _path(pid)
    if p.exists():
        p.unlink()
        if active_id() == pid:
            set_active("demo")
        return True
    return False
