"""Slow layer: organ damage accumulators over 10 years.

A representative week (7 day-profiles of glucose mean/SD, hydration, alcohol,
sleep debt, fat mass) is looped for `years`. Each accumulator `dmg_*` is the
cumulative hazard of that complication, so P(complication within 10 y)
= 1 - exp(-dmg). Coefficients and sources live in params.yaml (slow:).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

import numpy as np

from backend.schema.state import State, SLOW_FIELDS
from backend.engine.params import slow_params

ORGANS = ["dmg_eye", "dmg_kidney", "dmg_nerve", "dmg_cardio", "dmg_liver"]
ORGAN_LABEL = {"dmg_eye": "eyes", "dmg_kidney": "kidneys", "dmg_nerve": "nerves", "dmg_cardio": "heart", "dmg_liver": "liver"}


@dataclass
class DayProfile:
    mean_glucose: float
    sd_glucose: float
    frac_above_180: float = 0.0
    hydration: float = 0.9
    alcohol_g: float = 0.0
    sleep_debt: float = 0.0
    fat_mass: float = 18.0
    hypo_minutes: float = 0.0
    tir: float = 0.7


@dataclass
class WeekProfile:
    days: List[DayProfile]

    def mean(self, attr: str) -> float:
        return float(np.mean([getattr(d, attr) for d in self.days]))

    def total(self, attr: str) -> float:
        return float(np.sum([getattr(d, attr) for d in self.days]))

    def summary(self) -> Dict[str, float]:
        return {"mean_glucose": self.mean("mean_glucose"), "sd_glucose": self.mean("sd_glucose"),
                "tir": self.mean("tir"), "alcohol_g_week": self.total("alcohol_g"),
                "sleep_debt": self.mean("sleep_debt"), "hydration": self.mean("hydration"),
                "hypo_minutes_week": self.total("hypo_minutes"), "a1c_equivalent": a1c_equivalent(self)}


def adag_a1c(mean_glucose: float) -> float:
    """ADAG (Nathan 2008): A1c (%) = (mean glucose + 46.7) / 28.7."""
    return (mean_glucose + 46.7) / 28.7


def a1c_equivalent(week: WeekProfile, sp: Optional[Dict] = None) -> float:
    sp = sp or slow_params()
    return adag_a1c(week.mean("mean_glucose")) + sp["variability_gain"] * week.mean("sd_glucose") / 50.0 * 0.5


def weekly_hazard(week: WeekProfile, sp: Optional[Dict] = None) -> Dict[str, float]:
    """Cumulative-hazard increment for one week, per organ."""
    sp = sp or slow_params()
    a1c = a1c_equivalent(week, sp)
    alc_rel = week.total("alcohol_g") / sp["alcohol_ref_g_per_week"]
    fat_rel = max(week.mean("fat_mass") - sp["fat_ref_kg"], 0.0) / 10.0
    sleep_rel = week.mean("sleep_debt") / sp["sleep_debt_ref_h"]
    dehyd_rel = max(sp["hydration_ref"] - week.mean("hydration"), 0.0) / 0.15
    out = {}
    for organ, c in sp["organs"].items():
        extras = c["alcohol_w"] * alc_rel + c["fat_w"] * fat_rel + c["sleep_w"] * sleep_rel + c["hydration_w"] * dehyd_rel
        h = c["h0"] / 52.0 * np.exp(c["beta_per_a1c"] * (a1c - sp["reference_a1c"])) * (1.0 + extras)
        out[organ] = float(h)
    return out


@dataclass
class SlowResult:
    final_state: State
    probabilities: Dict[str, float]          # 10-year probability per organ
    yearly: List[Dict[str, float]]           # per-year cumulative hazards
    a1c_equivalent: float
    week_summary: Dict[str, float] = field(default_factory=dict)


def organ_probabilities(state: State) -> Dict[str, float]:
    return {k: float(1.0 - np.exp(-getattr(state, k))) for k in ORGANS}


def run_slow(week: WeekProfile, state: State, years: float = 10.0, reset: bool = True) -> SlowResult:
    """Loop the representative week for `years`. Accumulators start from zero
    (reset=True) so the result is the 10-year risk *from now* under this lifestyle."""
    sp = slow_params()
    s = state.copy()
    if reset:
        for k in ORGANS:
            setattr(s, k, 0.0)
    h = weekly_hazard(week, sp)
    n_weeks = int(round(years * 52))
    yearly = []
    for w in range(1, n_weeks + 1):
        for k in ORGANS:
            setattr(s, k, getattr(s, k) + h[k])
        if w % 52 == 0:
            yearly.append({"year": w // 52, **{k: getattr(s, k) for k in ORGANS}})
    s.hba1c = adag_a1c(week.mean("mean_glucose"))
    s.fat_mass = week.mean("fat_mass")
    s.sleep_debt = week.mean("sleep_debt")
    return SlowResult(final_state=s, probabilities=organ_probabilities(s), yearly=yearly,
                      a1c_equivalent=a1c_equivalent(week, sp), week_summary=week.summary())


def constant_week(mean_glucose: float, sd: float = 40.0, **kw) -> WeekProfile:
    return WeekProfile([DayProfile(mean_glucose=mean_glucose, sd_glucose=sd, **kw) for _ in range(7)])


def week_for_a1c(a1c: float, sd: float = 0.0) -> WeekProfile:
    """Constant week whose A1c-equivalent is exactly `a1c` (inverse ADAG, zero variability)."""
    return constant_week(a1c * 28.7 - 46.7, sd=sd)


def dcct_check(years: float = 10.0) -> Dict[str, float]:
    """A1c 9 vs 7: retinopathy risk ratio. DCCT reported a 76 % reduction."""
    st = State()
    r9 = run_slow(week_for_a1c(9.0), st, years)
    r7 = run_slow(week_for_a1c(7.0), st, years)
    p9, p7 = r9.probabilities["dmg_eye"], r7.probabilities["dmg_eye"]
    return {"p_retinopathy_a1c9": p9, "p_retinopathy_a1c7": p7, "risk_ratio": p7 / p9,
            "reduction_pct": 100.0 * (1.0 - p7 / p9), "hazard_ratio": r7.final_state.dmg_eye / r9.final_state.dmg_eye}
