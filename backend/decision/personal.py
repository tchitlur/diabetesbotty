"""Personalisation, in plain words: how this person's fitted parameters differ from the
population prior, and a population-parameter mode for "what would the answer be for the
average person with T1D?"."""
from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from backend.engine.params import FITTED_KEYS

# (fitted key, category, how to phrase it). ratio = fitted / prior; "more" means a larger parameter value.
PHRASES = {
    "si_tod0": ("insulin", "Your insulin works {pct} {better} overnight than the average person with T1D", "better", "less well", None),
    "si_tod1": ("insulin", "Your insulin works {pct} {better} during the day than average", "better", "less well", None),
    "si_tod2": ("insulin", "Your insulin works {pct} {better} in the evening than average", "better", "less well", None),
    "carb_ratio": ("food", "You absorb about {pct} {more} of the carbs you eat than average", "more", "less", None),
    "tau_carb": ("food", "Carbs hit your blood sugar about {mins} minutes {faster} than average", "slower", "faster", "minutes"),
    "exercise_mult": ("exercise", "Exercise lowers your glucose {pct} {more} than most", "more", "less", None),
    "alcohol_gain": ("alcohol", "Alcohol lowers you {pct} {more} than most", "more", "less", None),
    "basal_drift": ("insulin", "Your background insulin is doing {pct} {more} than it should", "more", "less", None),
    "sleep_debt_coef": ("sleep", "A short night hurts your insulin {pct} {more} than average", "more", "less", None),
}
PREFERRED = ["food", "insulin", "exercise", "sleep"]   # in this order; alcohol only under the rule below
WEIGHT = {"food": 1.0, "insulin": 0.95, "exercise": 0.85, "sleep": 0.8, "alcohol": 0.5}
CAP_PCT = 60.0                                          # above this the wording is "much more / much less than most"


def rank_score(f) -> float:
    """Magnitude (capped at 100) weighted by the category preference."""
    return min(float(f["magnitude"]), 100.0) * WEIGHT.get(f["category"], 0.5)


def _pct_words(pct: float, word: str) -> str:
    """'36% less' or, above the cap, 'much less than most' (never '150% more than most')."""
    if pct > CAP_PCT:
        return f"much {word}"
    return f"{int(round(pct))}% {word}"


def _phrase(k: str, fitted: float, prior: float) -> Optional[Dict[str, Any]]:
    ratio = fitted / prior if prior else 1.0
    if ratio <= 0:
        return None
    cat, tmpl, up, down, unit = PHRASES[k]
    pct = abs(ratio - 1.0) * 100.0
    word = up if ratio > 1 else down
    if unit == "minutes":
        mins = abs(fitted - prior)
        if mins < 3:
            return None
        text = tmpl.format(mins=int(round(mins)), faster=word)
        magnitude = pct
    else:
        if pct < 5:
            return None
        pw = _pct_words(pct, word)
        text = tmpl.format(pct=pw.split(" ", 1)[0], better=pw.split(" ", 1)[1], more=pw.split(" ", 1)[1]) if pct <= CAP_PCT else tmpl.replace("{pct} {better}", "much " + word).replace("{pct} {more}", "much " + word)
        if pct > CAP_PCT and " than average" in text:
            text = text.replace(" than average", " than most")
        magnitude = pct
    pos = 0.5 + 0.5 * max(-1.0, min(1.0, math.log2(ratio)))   # x2 or /2 sits at the ends
    return {"key": k, "category": cat, "text": text, "ratio": round(ratio, 3), "pos": round(pos, 3), "strength": round(abs(math.log2(ratio)), 3), "magnitude": round(magnitude, 1)}


def fact_candidates(twin) -> List[Dict[str, Any]]:
    """Every fitted-parameter deviation as a fact with a category and a magnitude (% deviation),
    plus, when a short night is actively holding insulin down today, that state as an insulin fact.
    Ranked by magnitude with the preferred categories first; alcohol is kept only when it is the
    single largest deviation and nothing else is above 20%."""
    fit = (twin.pt.fit or {}).get("params", {})
    out: List[Dict[str, Any]] = []
    for k in FITTED_KEYS:
        row = fit.get(k)
        if not row or not row.get("prior"):
            continue
        f = _phrase(k, float(row["mean"]), float(row["prior"]))
        if f:
            f["uncertainty"] = round(float(row.get("std", 0.0)) / abs(float(row["prior"])), 3)
            out.append(f)
    # the sleep-debt effect as it acts today: an insulin fact when sleep debt is real
    try:
        s = twin.medium_state()
        debt = float(s.sleep_debt)
        coef = float(twin.params.get("sleep_debt_coef", 0.2))
        drop = 100.0 * coef * min(debt, 3.0) / 2.5
        if debt >= 0.75 and drop >= 8:
            habit = str((twin.profile or {}).get("habit", ""))
            why = "after night shifts" if "night" in habit else "after short nights"
            prior = float(fit.get("sleep_debt_coef", {}).get("prior", 0.2) or 0.2)
            more = coef / prior if prior else 1.0
            tail = f" (a short night hurts your insulin {_pct_words(abs(more - 1) * 100, 'more' if more > 1 else 'less')} than most)" if abs(more - 1) >= 0.2 else ""
            out.append({"key": "insulin_today", "category": "insulin", "text": f"Your insulin is working {int(round(drop))}% below usual {why}{tail}",
                        "ratio": round(1 - drop / 100, 3), "pos": round(0.5 + 0.5 * max(-1.0, min(1.0, math.log2(max(1 - drop / 100, 0.01)))), 3),
                        "strength": round(abs(math.log2(max(1 - drop / 100, 0.01))), 3), "magnitude": round(drop + (abs(more - 1) * 100 if abs(more - 1) >= 0.2 else 0), 1), "uncertainty": None})
    except Exception:
        pass
    if any(f["key"] == "insulin_today" for f in out):
        out = [f for f in out if f["key"] != "sleep_debt_coef"]   # the same deviation, already inside the insulin-today fact
    ranked = sorted([f for f in out if f["category"] != "alcohol"], key=lambda f: -rank_score(f))
    alcohol = [f for f in out if f["category"] == "alcohol"]
    if alcohol:
        a = max(alcohol, key=lambda f: f["magnitude"])
        others_max = max((f["magnitude"] for f in ranked), default=0.0)
        if a["magnitude"] > others_max and others_max <= 20:
            ranked.insert(0, a)
    return ranked


def twin_summary(twin) -> Dict[str, Any]:
    """Three to five plain lines comparing the fit to the population prior, each with a marker
    position in [0, 1] (0.5 = average), plus how much data the fit learned from."""
    days = int(len(twin.pt.daily)) if twin.pt.daily is not None else 0
    lines = fact_candidates(twin)[:5]
    if len(lines) < 3:
        fit = (twin.pt.fit or {}).get("params", {})
        for k in FITTED_KEYS:
            if len(lines) >= 3:
                break
            if any(l["key"] == k for l in lines) or k not in fit:
                continue
            label = {"si_tod0": "overnight", "si_tod1": "during the day", "si_tod2": "in the evening"}.get(k)
            if label:
                lines.append({"key": k, "category": "insulin", "text": f"Your insulin works about like average {label}", "ratio": 1.0, "pos": 0.5, "strength": 0.0, "magnitude": 0.0, "uncertainty": None})
    learned = f"Learned from {days} days of your data" + (f", fitted on {twin.pt.fit.get('n_obs', 0):,} sensor readings" if twin.pt.fit else "")
    return {"lines": lines, "days": days, "learned": learned, "summary": (lines[0]["text"] if lines else "Not enough data to personalise yet") + ". " + learned + "."}


def assign_facts(candidates: Dict[str, List[Dict[str, Any]]], n_each: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    """Exactly `n_each` facts per person with no two people sharing the first fact's category: over
    every combination of first-fact choices, the one with the largest total (capped) magnitude,
    ties broken by the preferred category order."""
    ids = list(candidates)
    best, best_score = None, None
    def score(f):
        return rank_score(f)
    def rec(i: int, taken: set, chosen: Dict[str, Dict[str, Any]], total: float):
        nonlocal best, best_score
        if i == len(ids):
            if best_score is None or total > best_score:
                best, best_score = dict(chosen), total
            return
        pid = ids[i]
        for f in candidates[pid][:6]:
            if f["category"] in taken:
                continue
            chosen[pid] = f
            rec(i + 1, taken | {f["category"]}, chosen, total + score(f))
            del chosen[pid]
    rec(0, set(), {}, 0.0)
    if best is None:   # not enough distinct categories: fall back to each person's top fact
        best = {pid: candidates[pid][0] for pid in ids if candidates[pid]}
    out = {}
    for pid in ids:
        first = best.get(pid)
        rest = [f for f in candidates[pid] if first is None or f["key"] != first["key"]]
        # the second fact prefers another category when it is nearly as strong (variety over repetition)
        if first and rest:
            top = rank_score(rest[0])
            other = next((f for f in rest if f["category"] != first["category"] and rank_score(f) >= 0.85 * top), None)
            if other:
                rest = [other] + [f for f in rest if f is not other]
        out[pid] = ([first] if first else []) + rest[: max(n_each - 1, 0)]
    return out


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
