"""The five demo people (and the random one). Each is bound to one synthetic cohort patient
whose 90 days of sensor data the twin runs on; the twin is fitted the first time the person
is selected (or in the background at startup). The "signature moment" is the one question
that shows what is special about that person; the chat's help popover leads with it."""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional

from backend.config import COHORT_DIR

log = logging.getLogger("glucopilot.personas")

PERSONAS: List[Dict[str, Any]] = [
    {"id": "demo", "patient_id": "demo", "name": "Alex", "avatar": "🧑‍💻", "age": 34, "sex": "M", "weight_kg": 96.0, "height_cm": 180.0,
     "occupation": "Software engineer", "habit": "runs before work", "t1d_years": 12, "sensor_days": 90,
     "carb_ratio_g_per_u": 37.0, "correction_factor_mgdl_per_u": 50.0, "target_low": 70.0, "target_high": 180.0,
     "signature": "Run at 7 tomorrow for 30 min?", "created_at": "2025-08-01T00:00"},
    {"id": "priya", "patient_id": "p07", "name": "Priya", "avatar": "🚴", "age": 24, "sex": "F", "weight_kg": 68.0, "height_cm": 165.0,
     "occupation": "Nursing student", "habit": "cycles to work", "t1d_years": 6, "sensor_days": 90,
     "carb_ratio_g_per_u": 10.0, "correction_factor_mgdl_per_u": 45.0, "target_low": 70.0, "target_high": 180.0,
     "signature": "Can I cycle home without a snack?", "created_at": "2025-08-01T00:01"},
    {"id": "ken", "patient_id": "p16", "name": "Ken", "avatar": "🧑‍🍳", "age": 40, "sex": "M", "weight_kg": 108.0, "height_cm": 178.0,
     "occupation": "Line cook", "habit": "skips breakfast a lot", "t1d_years": 13, "sensor_days": 90,
     "carb_ratio_g_per_u": 14.0, "correction_factor_mgdl_per_u": 40.0, "target_low": 70.0, "target_high": 160.0,
     "signature": "What if I skip breakfast?", "created_at": "2025-08-01T00:02"},
    {"id": "marcus", "patient_id": "p13", "name": "Marcus", "avatar": "🧑‍⚕️", "age": 48, "sex": "M", "weight_kg": 84.0, "height_cm": 176.0,
     "occupation": "Nurse", "habit": "night-shift sleep schedule", "t1d_years": 18, "sensor_days": 90,
     "carb_ratio_g_per_u": 8.0, "correction_factor_mgdl_per_u": 35.0, "target_low": 70.0, "target_high": 180.0,
     "signature": "Will I go low during my night shift?", "created_at": "2025-08-01T00:03"},
    {"id": "zara", "patient_id": "p17", "name": "Zara", "avatar": "☕", "age": 19, "sex": "F", "weight_kg": 59.0, "height_cm": 163.0,
     "occupation": "Barista", "habit": "coffee all day", "t1d_years": 6, "sensor_days": 90,
     "carb_ratio_g_per_u": 18.0, "correction_factor_mgdl_per_u": 60.0, "target_low": 70.0, "target_high": 180.0,
     "signature": "Is a fourth coffee a bad idea?", "created_at": "2025-08-01T00:04"},
]
PERSONA_IDS = [p["id"] for p in PERSONAS]

# for "Random new person"
_NAMES_F = ["Maya", "Sofia", "Leila", "Nadia", "Hana", "Ines", "Rosa", "Aiko", "Elena", "Tess"]
_NAMES_M = ["Omar", "Luca", "Theo", "Ravi", "Jonas", "Mateo", "Kofi", "Ilya", "Sam", "Diego"]
_JOBS = [("Teacher", "🧑‍🏫", "long days on their feet"), ("Delivery driver", "🚚", "eats on the road"), ("Architect", "📐", "late-night deadlines"),
         ("Musician", "🎸", "gigs that end after midnight"), ("Gardener", "🌱", "outdoors all day"), ("Accountant", "🧾", "desk lunches"),
         ("Physiotherapist", "🤸", "trains most evenings"), ("Chef", "🍳", "tastes everything"), ("Student", "🎓", "irregular meals"),
         ("Pharmacist", "💊", "shift work"), ("Firefighter", "🚒", "24-hour shifts"), ("Journalist", "📰", "coffee-fuelled deadlines")]
_AVATARS_ANY = ["🧑", "👩", "👨", "🧔", "👩‍🦱", "👨‍🦱", "🧑‍🦰"]


def random_body(rng: random.Random, used_names: List[str]) -> Dict[str, Any]:
    """A plausible new person, drawn at random; the cohort patient is matched by sex and weight."""
    sex = rng.choice(["F", "M"])
    names = [n for n in (_NAMES_F if sex == "F" else _NAMES_M) if n not in used_names] or (_NAMES_F if sex == "F" else _NAMES_M)
    job, avatar, habit = rng.choice(_JOBS)
    age = rng.randint(18, 62)
    weight = round(rng.uniform(52, 105) if sex == "F" else rng.uniform(60, 115), 1)
    height = round(rng.uniform(155, 178) if sex == "F" else rng.uniform(165, 192))
    cr = float(rng.choice([8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20]))
    return {"name": rng.choice(names), "avatar": avatar, "age": age, "sex": sex, "weight_kg": weight, "height_cm": float(height),
            "occupation": job, "habit": habit, "t1d_years": rng.randint(1, max(2, age - 8)), "sensor_days": 90,
            "carb_ratio_g_per_u": cr, "correction_factor_mgdl_per_u": float(rng.choice([35, 40, 45, 50, 55, 60])),
            "target_low": 70.0, "target_high": float(rng.choice([160, 180, 180, 180])),
            "signature": rng.choice(["Can I have pizza for dinner?", "What if I skip lunch?", "Is a second coffee okay?", "Run at 7 tomorrow?"])}


_PREFIT: Dict[str, Any] = {"thread": None, "done": False}


def prefit_in_background(fit_one) -> None:
    """Fit the four unfitted personas one by one (about 10 s each) so a switch is instant later."""
    if _PREFIT["thread"] is not None:
        return

    def run():
        for p in PERSONAS:
            if p["patient_id"] == "demo":
                continue
            try:
                fit_one(p["id"])
            except Exception as ex:   # a failed prefit only means a slower first switch
                log.warning("prefit of %s failed: %s", p["id"], type(ex).__name__)
        _PREFIT["done"] = True

    t = threading.Thread(target=run, name="persona-prefit", daemon=True)
    _PREFIT["thread"] = t
    t.start()
