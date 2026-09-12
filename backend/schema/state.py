"""The single State contract shared by every layer.

Fast layer   : updated every 5 minutes by the ODE engine.
Medium layer : updated daily.
Slow layer   : dimensionless exposure accumulators integrated over years.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from typing import Dict, List

FAST_FIELDS: List[str] = [
    "glucose",          # mg/dL
    "plasma_insulin",   # mU/L
    "gut_carbs_1",      # g
    "gut_carbs_2",      # g
    "liver_glycogen",   # g (0..max)
    "muscle_glycogen",  # g (0..max)
    "blood_alcohol",    # g/dL (BAC)
    "caffeine",         # mg
    "ketones",          # mmol/L
    "hydration",        # 0..1
    "energy_score",     # 0..100
]

MEDIUM_FIELDS: List[str] = [
    "sleep_debt",           # hours
    "insulin_sensitivity",  # multiplier, 1.0 = baseline
    "training_load",        # arbitrary units
    "fat_mass",             # kg
    "lean_mass",            # kg
    "hba1c",                # %
]

SLOW_FIELDS: List[str] = [
    "dmg_eye",
    "dmg_kidney",
    "dmg_nerve",
    "dmg_cardio",
    "dmg_liver",
]

ALL_FIELDS: List[str] = FAST_FIELDS + MEDIUM_FIELDS + SLOW_FIELDS

UNITS: Dict[str, str] = {
    "glucose": "mg/dL", "plasma_insulin": "mU/L", "gut_carbs_1": "g", "gut_carbs_2": "g",
    "liver_glycogen": "g", "muscle_glycogen": "g", "blood_alcohol": "g/dL", "caffeine": "mg",
    "ketones": "mmol/L", "hydration": "0-1", "energy_score": "0-100",
    "sleep_debt": "h", "insulin_sensitivity": "x", "training_load": "au",
    "fat_mass": "kg", "lean_mass": "kg", "hba1c": "%",
    "dmg_eye": "exposure", "dmg_kidney": "exposure", "dmg_nerve": "exposure",
    "dmg_cardio": "exposure", "dmg_liver": "exposure",
}


@dataclass
class State:
    # ---- fast layer ----
    glucose: float = 120.0
    plasma_insulin: float = 10.0
    gut_carbs_1: float = 0.0
    gut_carbs_2: float = 0.0
    liver_glycogen: float = 80.0
    muscle_glycogen: float = 350.0
    blood_alcohol: float = 0.0
    caffeine: float = 0.0
    ketones: float = 0.1
    hydration: float = 0.9
    energy_score: float = 75.0
    # ---- medium layer ----
    sleep_debt: float = 0.0
    insulin_sensitivity: float = 1.0
    training_load: float = 10.0
    fat_mass: float = 18.0
    lean_mass: float = 57.0
    hba1c: float = 7.0
    # ---- slow layer ----
    dmg_eye: float = 0.0
    dmg_kidney: float = 0.0
    dmg_nerve: float = 0.0
    dmg_cardio: float = 0.0
    dmg_liver: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "State":
        names = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in d.items() if k in names})

    def copy(self) -> "State":
        return State.from_dict(self.to_dict())

    def fast_vector(self) -> List[float]:
        return [getattr(self, k) for k in FAST_FIELDS]

    def set_fast_vector(self, vec) -> None:
        for k, v in zip(FAST_FIELDS, vec):
            setattr(self, k, float(v))
