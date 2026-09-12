"""Permission engine: for a proposed event, simulate do-nothing, the event,
and variants (delay 1 h, halve amount, add 15 g fast carbs, add a 20 g
pre-workout snack); score each with Monte Carlo; fill a PermissionCard."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.schema.events import Event
from backend.schema.api import PermissionCard, EventModel, MiniCurve
from backend.engine.montecarlo import MCResult
from backend.engine.slow import run_slow, WeekProfile, DayProfile, ORGANS
from backend.safety.gate import load_rules
from backend.safety.explain import factors_from_mc, confidence_score, data_inventory

HYPER_BREACH_PROB = 0.25


@dataclass
class Scenario:
    name: str
    condition: str
    events: List[Event]          # extra events on top of the session
    mc: Optional[MCResult] = None
    p_hypo: float = 0.0
    p_hyper: float = 0.0
    tir: float = 0.0
    energy: float = 0.0
    blocked: bool = False

    def passes(self, p_hypo_max: float) -> bool:
        return (not self.blocked) and self.p_hypo < p_hypo_max and self.p_hyper < HYPER_BREACH_PROB

    def score(self) -> float:
        return self.tir + self.energy / 100.0 - 2.0 * self.p_hypo - 0.5 * self.p_hyper


def _shift(e: Event, minutes: float) -> Event:
    return e.copy(start_time=(e.start + timedelta(minutes=minutes)).isoformat(timespec="minutes"))


def _halve(e: Event) -> Event:
    kw = {}
    for k in ("carbs_g", "fat_g", "protein_g", "fiber_g", "alcohol_g", "caffeine_mg", "insulin_units"):
        v = getattr(e, k)
        if v:
            kw[k] = v / 2.0
    if e.type == "exercise":
        kw["duration_min"] = max(e.duration_min, 30.0) / 2.0
    lbl = e.label or e.type
    return e.copy(label=f"half {lbl}", **kw)


def build_variants(e: Event) -> List[Tuple[str, str, List[Event]]]:
    """(name, condition text, events)."""
    fast_carbs = Event(type="meal", start_time=e.start_time, carbs_g=15, duration_min=5, uncertainty=0.1, source="tap", label="15 g fast carbs")
    out: List[Tuple[str, str, List[Event]]] = [
        ("delay_1h", "wait an hour first", [_shift(e, 60)]),
        ("halve", "have half as much", [_halve(e)]),
    ]
    if e.type == "exercise":
        snack = Event(type="meal", start_time=(e.start - timedelta(minutes=15)).isoformat(timespec="minutes"), carbs_g=20, duration_min=5, uncertainty=0.1, source="tap", label="20 g pre-workout snack")
        out.append(("pre_workout_snack_20g", "eat a 20 g snack 15 min before", [snack, e]))
        out.append(("fast_carbs_15g", "take 15 g fast carbs at the start", [fast_carbs, e]))
    elif e.type == "alcohol":
        bed = Event(type="meal", start_time=(e.start + timedelta(minutes=max(e.duration_min, 60) + 30)).isoformat(timespec="minutes"), carbs_g=15, duration_min=5, uncertainty=0.1, source="tap", label="15 g carbs at bedtime")
        out.append(("fast_carbs_15g", "eat 15 g carbs before bed, no bolus", [e, bed]))
        out.append(("halve_plus_carbs", "have half as much and 15 g carbs before bed", [_halve(e), bed]))
    elif e.type in ("meal", "caffeine"):
        pass
    else:
        out.append(("fast_carbs_15g", "take 15 g fast carbs now", [fast_carbs, e]))
    return out


def _horizon_for(e: Event) -> int:
    if e.type == "alcohol":
        return 12 * 60
    return 8 * 60


def _long_term_delta(twin, e: Event) -> Dict[str, float]:
    """10-year organ-risk change if this event were repeated every week."""
    base = twin.week_profile()
    r0 = run_slow(base, twin.medium_state())
    days = [DayProfile(**{**d.__dict__}) for d in base.days]
    wd = e.start.weekday()
    d = days[wd]
    if e.type == "alcohol":
        d.alcohol_g += e.alcohol_g
        d.hydration -= 0.02 * e.alcohol_g / 14.0
        d.mean_glucose += 2.0 * e.carbs_g / 13.0
        d.sd_glucose += 3.0 * e.alcohol_g / 14.0
    elif e.type == "meal":
        d.mean_glucose += 0.25 * e.carbs_g
        d.sd_glucose += 0.15 * e.carbs_g
    elif e.type == "exercise":
        d.mean_glucose -= 4.0 * max(e.duration_min, 30) / 30.0
        d.sd_glucose += 2.0
        d.fat_mass -= 0.02 * max(e.duration_min, 30) / 30.0
    elif e.type == "caffeine":
        d.sleep_debt += 0.3 * e.caffeine_mg / 200.0
        d.mean_glucose += 1.5 * e.caffeine_mg / 200.0
    r1 = run_slow(WeekProfile(days), twin.medium_state())
    return {k: round(100.0 * (r1.probabilities[k] - r0.probabilities[k]), 3) for k in ORGANS}


def evaluate_permission(twin, proposed: Event, stale_override: Optional[float] = None, n: int = 200) -> PermissionCard:
    rules = load_rules()["hard_rules"]
    p_hypo_max = rules["hypo_probability_max_for_approval"]
    gate = twin.gate(proposed.type, stale_override)
    inv = data_inventory(True, twin.staleness_min(stale_override), bool(twin.posterior), twin.residual is not None,
                         twin.events_24h_counts())
    if gate.action == "request_data":
        card = PermissionCard(verdict="request_data", condition=gate.instruction, proposed=EventModel(**proposed.to_dict()),
                              explanation=f"Not deciding: {gate.reason}. {gate.instruction}", gate=gate.to_dict(),
                              data_used=inv["data_used"], data_missing=[gate.what] + inv["data_missing"], confidence=0.0)
        twin.remember_card(card)
        return card
    if gate.action == "escalate":
        card = PermissionCard(verdict="escalate", condition=gate.instruction, proposed=EventModel(**proposed.to_dict()),
                              explanation=f"Escalating: {gate.reason}. {gate.instruction}", gate=gate.to_dict(),
                              data_used=inv["data_used"], data_missing=inv["data_missing"], confidence=0.0)
        twin.remember_card(card)
        return card

    horizon = _horizon_for(proposed)
    scenarios: List[Scenario] = [Scenario("do_nothing", "", []), Scenario("proposed", "", [proposed])]
    for name, cond, evs in build_variants(proposed):
        scenarios.append(Scenario(name, cond, evs))
    for i, sc in enumerate(scenarios):
        sc.mc = twin.forecast(extra=sc.events, horizon_min=horizon, n=n, seed=i)
        sc.p_hypo, sc.p_hyper, sc.tir, sc.energy = sc.mc.p_hypo, sc.mc.p_hyper, sc.mc.tir, sc.mc.energy
    do_nothing, prop = scenarios[0], scenarios[1]
    variants = scenarios[2:]

    # event-type hard rules turn into blocks on the proposed scenario (or all of them)
    hard_block_all = False
    if gate.rule == "exercise_glucose_floor":
        prop.blocked = True
        for v in variants:
            if not any(x.type == "meal" for x in v.events):
                v.blocked = True
    if gate.rule == "alcohol_ketone_ceiling":
        hard_block_all = True

    if hard_block_all:
        verdict, best, condition = "denied", min(variants + [prop], key=lambda s: s.p_hypo), gate.instruction
    elif prop.passes(p_hypo_max):
        verdict, best, condition = "approved", prop, ""
    else:
        ok = [v for v in variants if v.passes(p_hypo_max)]
        if ok:
            best = max(ok, key=lambda s: s.score())
            verdict, condition = "approved_with_condition", best.condition
        else:
            best = min(variants, key=lambda s: (s.p_hypo, -s.score()))
            verdict, condition = "denied", f"even the safest option ({best.condition}) leaves P(hypo) at {best.p_hypo:.0%}"
    if gate.rule == "exercise_glucose_floor" and verdict != "denied":
        condition = (gate.instruction + " " + condition).strip()

    alternative = None
    if proposed.type == "exercise" and verdict != "approved":
        alternative = alternative_window(twin, proposed)
        if alternative is not None:
            tag = "safe alternative" if alternative["p_hypo"] < p_hypo_max else "best alternative window"
            condition = (condition + f"; {tag}: {alternative['start'][11:16]} (P(hypo) {alternative['p_hypo']:.0%})").strip("; ")
    best_event = next((x for x in best.events if x.type == proposed.type), None) or proposed
    factors = factors_from_mc(prop.mc)
    conf = confidence_score(twin.pt.cgm.data_quality, twin.posterior, prop.mc, twin.staleness_min(stale_override), twin.drift_status().score)
    explanation = _explain(verdict, proposed, prop, best, do_nothing, condition)
    long_term = _long_term_delta(twin, proposed)
    card = PermissionCard(
        verdict=verdict, condition=condition, proposed=EventModel(**proposed.to_dict()),
        best_variant=EventModel(**best_event.to_dict()), plan_events=[EventModel(**x.to_dict()) for x in best.events], variant_name=best.name,
        p_hypo=round(best.p_hypo, 3), p_hyper=round(best.p_hyper, 3), tir=round(best.tir, 3), energy=round(best.energy, 1),
        long_term_delta=long_term, confidence=conf, factors=factors,
        data_used=inv["data_used"], data_missing=inv["data_missing"],
        mini_curve=MiniCurve(times=prop.mc.times, do_nothing=_r(do_nothing.mc.median), with_event=_r(prop.mc.median),
                             best_variant=_r(best.mc.median), p10=_r(prop.mc.p10), p90=_r(prop.mc.p90)),
        variants=[{"name": s.name, "condition": s.condition, "p_hypo": round(s.p_hypo, 3), "p_hyper": round(s.p_hyper, 3),
                   "tir": round(s.tir, 3), "energy": round(s.energy, 1), "min_glucose": round(float(np.median(s.mc.min_glucose_samples)), 1),
                   "passes": s.passes(p_hypo_max), "blocked": s.blocked} for s in scenarios],
        explanation=explanation, gate=gate.to_dict())
    if alternative is not None:
        card.variants.append({"name": "alternative_window", "condition": f"move to {alternative['start'][11:16]}", "p_hypo": alternative["p_hypo"],
                              "p_hyper": alternative["p_hyper"], "tir": alternative["tir"], "energy": alternative["energy"],
                              "min_glucose": alternative["min_glucose"], "passes": alternative["p_hypo"] < p_hypo_max, "blocked": False,
                              "start": alternative["start"]})
    twin.remember_card(card)
    return card


def alternative_window(twin, e: Event, max_shift_h: float = 12.0):
    """Search later start times (30-min steps) for the same session; batched
    deterministic pass first, Monte Carlo on the best few."""
    from backend.engine.fast import IDX
    from backend.engine import fast as F
    from backend.engine.simulate import events_to_inputs, state_params
    from backend.engine.montecarlo import run_monte_carlo
    s, _ = twin.state_now()
    p = state_params(twin.medium_state(), twin.params)
    shifts = [30 * k for k in range(1, int(max_shift_h * 2) + 1)]
    cands = [_shift(e, m) for m in shifts]
    last = max(c.start for c in cands) + timedelta(minutes=max(e.duration_min, 30) + 4 * 60)
    horizon = int((last - twin.now).total_seconds() // 60)
    n_steps = horizon // 5
    ctx = twin.context_events()
    inputs = np.stack([events_to_inputs(sorted(ctx + [c], key=lambda x: x.start), twin.now, n_steps, 5, p) for c in cands], axis=1)
    x0 = np.repeat(twin.hidden_now()[None, :], len(cands), axis=0)
    X = F.integrate(x0, inputs, p, 5, substeps=2)
    G = F.glucose_mgdl(X, p)
    # score the window from the session start to 4 h after it
    scores = []
    for i, c in enumerate(cands):
        a = int((c.start - twin.now).total_seconds() // 300)
        b = min(a + int((max(e.duration_min, 30) + 240) // 5), G.shape[0] - 1)
        seg = G[a:b + 1, i]
        scores.append((float(seg.min()), i))
    scores.sort(reverse=True)
    best = None
    for gmin, i in scores[:4]:
        c = cands[i]
        mc = run_monte_carlo(s, sorted(ctx + [c], key=lambda x: x.start), twin.params, twin.posterior,
                             horizon_min=int((c.start - twin.now).total_seconds() // 60) + int(max(e.duration_min, 30)) + 240,
                             n=120, t0=twin.now, hidden=twin.hidden_now(), seed=7 + i)
        # only the window from the session start onward counts (the night before is not this decision)
        a = int((c.start - twin.now).total_seconds() // 300)
        p_hypo = float(np.mean(mc.glucose_samples[:, a:].min(axis=1) < 70))
        row = {"start": c.start_time, "p_hypo": round(p_hypo, 3), "p_hyper": round(mc.p_hyper, 3), "tir": round(mc.tir, 3),
               "energy": round(mc.energy, 1), "min_glucose": round(gmin, 1)}
        if best is None or row["p_hypo"] < best["p_hypo"]:
            best = row
        if p_hypo < 0.05:
            return row
    return best


def _r(a) -> List[float]:
    return [round(float(x), 1) for x in a]


def _explain(verdict: str, proposed: Event, prop: Scenario, best: Scenario, nothing: Scenario, condition: str) -> str:
    lbl = proposed.label or proposed.type
    med_min = float(np.median(prop.mc.min_glucose_samples))
    base = (f"With '{lbl}' as proposed, P(glucose < 70 within {len(prop.mc.times) * 5 // 60} h) = {prop.p_hypo:.0%} "
            f"(do nothing: {nothing.p_hypo:.0%}); median low point {med_min:.0f} mg/dL.")
    if verdict == "approved":
        return base + " That is under the 5 % limit with no hyper breach, so it is approved."
    if verdict == "approved_with_condition":
        return base + f" Approved only if you {condition}: that brings P(hypo) to {best.p_hypo:.0%}."
    return base + f" Denied: {condition}."
