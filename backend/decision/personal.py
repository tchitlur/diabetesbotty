"""Personalisation, in plain words: how this person's fitted parameters differ from the
population prior, and a population-parameter mode for "what would the answer be for the
average person with T1D?"."""
from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from backend.engine.params import FITTED_KEYS

# (fitted key, how to phrase it). ratio = fitted / prior; "more" means a larger parameter value.
PHRASES = {
    "si_tod0": ("Your insulin works {pct}% {better} overnight than the average person with T1D", "better", "less well", None),
    "si_tod1": ("Your insulin works {pct}% {better} during the day than average", "better", "less well", None),
    "si_tod2": ("Your insulin works {pct}% {better} in the evening than average", "better", "less well", None),
    "carb_ratio": ("You absorb about {pct}% {more} of the carbs you eat than average", "more", "less", None),
    "tau_carb": ("Carbs hit your blood sugar about {mins} minutes {faster} than average", "slower", "faster", "minutes"),
    "exercise_mult": ("Exercise lowers your glucose {pct}% {more} than most", "more", "less", None),
    "alcohol_gain": ("Alcohol lowers you {pct}% {more} than most", "more", "less", None),
    "basal_drift": ("Your background insulin is doing {pct}% {more} than it should", "more", "less", None),
    "sleep_debt_coef": ("A short night hurts your insulin {pct}% {more} than average", "more", "less", None),
}


def twin_summary(twin) -> Dict[str, Any]:
    """Three to five plain lines comparing the fit to the population prior, each with a marker
    position in [0, 1] (0.5 = average), plus how much data the fit learned from."""
    fit = (twin.pt.fit or {}).get("params", {})
    days = int(len(twin.pt.daily)) if twin.pt.daily is not None else 0
    lines: List[Dict[str, Any]] = []
    for k in FITTED_KEYS:
        row = fit.get(k)
        if not row or not row.get("prior"):
            continue
        fitted, prior = float(row["mean"]), float(row["prior"])
        ratio = fitted / prior if prior else 1.0
        if ratio <= 0:
            continue
        tmpl, up, down, unit = PHRASES[k]
        pct = abs(ratio - 1.0) * 100.0
        word = up if ratio > 1 else down
        if unit == "minutes":
            mins = abs(fitted - prior)
            if mins < 3:
                continue
            text = tmpl.format(mins=int(round(mins)), faster=word)
        else:
            if pct < 5:
                continue
            text = tmpl.format(pct=int(round(pct)), better=word, more=word)
        pos = 0.5 + 0.5 * max(-1.0, min(1.0, math.log2(ratio) / 1.0))   # x2 or /2 sits at the ends
        lines.append({"key": k, "text": text, "ratio": round(ratio, 3), "pos": round(pos, 3), "strength": round(abs(math.log2(ratio)), 3),
                      "uncertainty": round(float(row.get("std", 0.0)) / abs(prior), 3) if prior else None})
    lines.sort(key=lambda r: -r["strength"])
    lines = lines[:5]
    if len(lines) < 3:
        # always say something: the closest-to-average parameters, phrased as "about average"
        for k in FITTED_KEYS:
            if len(lines) >= 3:
                break
            if any(l["key"] == k for l in lines) or k not in fit:
                continue
            label = {"si_tod0": "overnight", "si_tod1": "during the day", "si_tod2": "in the evening"}.get(k)
            if label:
                lines.append({"key": k, "text": f"Your insulin works about like average {label}", "ratio": 1.0, "pos": 0.5, "strength": 0.0, "uncertainty": None})
    learned = f"Learned from {days} days of your data" + (f", fitted on {twin.pt.fit.get('n_obs', 0):,} sensor readings" if twin.pt.fit else "")
    return {"lines": lines, "days": days, "learned": learned, "summary": (lines[0]["text"] if lines else "Not enough data to personalise yet") + ". " + learned + "."}


def population_params(twin) -> Dict[str, Any]:
    """The same parameter dict with every fitted key reset to its population prior."""
    p = dict(twin.params)
    fit = (twin.pt.fit or {}).get("params", {})
    for k in FITTED_KEYS:
        if k in fit and fit[k].get("prior") is not None:
            p[k] = float(fit[k]["prior"])
    return p


@contextmanager
def as_population(twin):
    """Temporarily run the twin on population parameters: no fit, no learned correction,
    the state re-estimated with those parameters. Restores everything afterwards."""
    saved = (twin.params, twin.posterior, twin.residual, twin._ukf, twin._state_cache, twin._cache)
    try:
        twin.params = population_params(twin)
        twin.posterior = {}
        twin.residual = None
        twin._ukf = None
        twin._state_cache = None
        twin._cache = {}
        yield twin
    finally:
        twin.params, twin.posterior, twin.residual, twin._ukf, twin._state_cache, twin._cache = saved
