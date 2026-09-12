"""Load params.yaml and flatten it into the dict the ODE right-hand side uses.

`build_params(overrides)` returns a flat dict of floats (or (B,) numpy arrays
for batched simulation). Patient-level keys (body_weight_kg, si_tod0..2,
carb_ratio, tau_carb, exercise_mult, alcohol_gain, basal_drift, ...) can be
overridden; Hovorka constants can be overridden too (the synthetic cohort does
this to give every virtual patient a different "true" physiology).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Optional

import yaml

from backend.config import PARAMS_PATH

FITTED_KEYS = [
    "si_tod0", "si_tod1", "si_tod2",
    "carb_ratio", "tau_carb", "exercise_mult", "alcohol_gain", "basal_drift", "sleep_debt_coef",
]

FITTED_BOUNDS = {
    "si_tod0": (0.4, 2.0), "si_tod1": (0.4, 2.0), "si_tod2": (0.4, 2.0),
    "carb_ratio": (0.4, 1.2), "tau_carb": (20.0, 90.0), "exercise_mult": (0.3, 2.5),
    "alcohol_gain": (0.2, 2.5), "basal_drift": (0.5, 1.6), "sleep_debt_coef": (0.0, 0.5),
}


@lru_cache(maxsize=1)
def load_yaml() -> Dict[str, Any]:
    with open(PARAMS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _flatten_extensions(ext: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for group, sub in ext.items():
        for k, v in sub.items():
            out[f"{group}_{k}"] = float(v)
    return out


def build_params(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    y = load_yaml()
    p: Dict[str, Any] = {}
    for k, v in y["hovorka"].items():
        p[k] = float(v)
    pat = y["patient"]
    p["BW"] = float(pat["body_weight_kg"])
    p["basal_u_per_h"] = float(pat["basal_u_per_h"])
    p["carb_ratio_g_per_u"] = float(pat["carb_ratio_g_per_u"])
    p["si_tod0"], p["si_tod1"], p["si_tod2"] = [float(x) for x in pat["si_tod"]]
    for k in ["carb_ratio", "tau_carb", "exercise_mult", "alcohol_gain", "basal_drift", "sleep_debt_coef"]:
        p[k] = float(pat[k])
    p.update(_flatten_extensions(y["extensions"]))
    # medium-layer state that modulates the fast layer (overridden from State each call)
    p["insulin_sensitivity"] = 1.0
    p["sleep_debt"] = 0.0
    if overrides:
        for k, v in overrides.items():
            if k == "si_tod" and isinstance(v, (list, tuple)):
                p["si_tod0"], p["si_tod1"], p["si_tod2"] = [float(x) for x in v]
            elif k == "body_weight_kg":
                p["BW"] = v
            else:
                p[k] = v
    return p


def medium_params() -> Dict[str, float]:
    return {k: float(v) for k, v in load_yaml()["medium"].items()}


def slow_params() -> Dict[str, Any]:
    return load_yaml()["slow"]


def cohort_ranges() -> Dict[str, Any]:
    return load_yaml()["cohort_ranges"]
