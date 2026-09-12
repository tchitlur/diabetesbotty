"""Planner: given tomorrow's calendar blocks, grid-search the workout start
time (30-min steps), snack placement and drink cutoff to maximise
TIR + energy subject to P(hypo) < 0.05 and the safety rules.

All candidate days are integrated in one batch (deterministic, personalised
parameters); the top candidates are then checked with Monte Carlo."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.schema.events import Event
from backend.schema.state import State
from backend.schema.api import PlanResponse, TimelineBlock, EventModel
from backend.engine import fast
from backend.engine.fast import IDX
from backend.engine.simulate import events_to_inputs, state_params, pack_trajectories
from backend.engine.montecarlo import run_monte_carlo
from backend.safety.gate import load_rules

DT = 5


def typical_day_events(twin, day: datetime) -> List[Event]:
    """Tomorrow's routine: the patient's usual meals (median time/carbs over the
    last 14 days) with boluses per carb ratio, plus the usual basal."""
    ev = [e for e in twin.pt.events if twin.now - timedelta(days=14) <= e.start <= twin.now]
    cr = twin.params.get("carb_ratio_g_per_u", 10.0)
    out: List[Event] = []
    for name, lo, hi in (("breakfast", 5, 10), ("lunch", 11, 15), ("dinner", 17, 22)):
        meals = [e for e in ev if e.type == "meal" and lo <= e.start.hour < hi and e.carbs_g >= 25]
        if not meals:
            continue
        h = float(np.median([e.start.hour + e.start.minute / 60.0 for e in meals]))
        t = day.replace(hour=int(h), minute=int((h % 1) * 60) // 5 * 5)
        carbs = float(np.median([e.carbs_g for e in meals]))
        fat = float(np.median([e.fat_g for e in meals]))
        prot = float(np.median([e.protein_g for e in meals]))
        out.append(Event(type="meal", start_time=t.isoformat(timespec="minutes"), duration_min=15, carbs_g=carbs, fat_g=fat, protein_g=prot, uncertainty=0.3, source="synthetic", label=f"usual {name}"))
        out.append(Event(type="insulin", start_time=t.isoformat(timespec="minutes"), insulin_units=carbs / cr, insulin_kind="bolus", uncertainty=0.1, source="synthetic", label=f"bolus for {name}"))
    out.append(Event(type="sleep", start_time=(day - timedelta(hours=1)).isoformat(timespec="minutes"), duration_min=450, sleep_hours=7.5, source="synthetic", label="sleep"))
    return out


def _free(t: datetime, dur_min: float, blocks: List[Dict[str, str]]) -> bool:
    end = t + timedelta(minutes=dur_min)
    for b in blocks:
        bs, be = datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])
        if t < be and end > bs:
            return False
    return True


def plan_day(twin, day: Optional[datetime] = None, blocks: Optional[List[Dict[str, str]]] = None,
             workout: Optional[Dict[str, Any]] = None, drinks: int = 0) -> PlanResponse:
    day = day or (twin.now + timedelta(days=1)).replace(hour=0, minute=0)
    blocks = blocks or [{"start": day.replace(hour=9).isoformat(), "end": day.replace(hour=12).isoformat(), "label": "work"},
                        {"start": day.replace(hour=13).isoformat(), "end": day.replace(hour=17).isoformat(), "label": "work"}]
    workout = workout or {"kind": "aerobic", "duration_min": 30, "intensity": 0.6}
    routine = typical_day_events(twin, day)
    rules = load_rules()["hard_rules"]

    # ---- state at the start of the day: deterministic run from now
    lead = int((day - twin.now).total_seconds() // 60)
    s_now, _ = twin.state_now()
    hidden = twin.hidden_now()
    p = state_params(twin.medium_state(), twin.params)
    if lead > 0:
        tr = twin.deterministic(extra=None, horizon_min=lead)
        s0 = tr.final_state()
        for k in ("sleep_debt", "insulin_sensitivity", "training_load", "fat_mass", "lean_mass", "hba1c"):
            setattr(s0, k, getattr(s_now, k))
        hidden = tr.hidden_final
    else:
        s0 = s_now

    # ---- candidates
    dur = float(workout.get("duration_min", 30))
    starts = [day.replace(hour=h, minute=m) for h in range(6, 21) for m in (0, 30) if _free(day.replace(hour=h, minute=m), dur, blocks)]
    snack_opts = ["none", "pre_workout_20g", "bedtime_15g"]
    cutoffs = [20, 21, 22] if drinks > 0 else [None]
    cands: List[Tuple[datetime, str, Optional[int], List[Event]]] = []
    for st in starts:
        for sn in snack_opts:
            for co in cutoffs:
                evs = list(routine)
                evs.append(Event(type="exercise", start_time=st.isoformat(timespec="minutes"), duration_min=dur, exercise_kind=workout.get("kind", "aerobic"), intensity=float(workout.get("intensity", 0.6)), uncertainty=0.15, source="tap", label=f"{workout.get('kind', 'aerobic')} {int(dur)} min"))
                if sn == "pre_workout_20g":
                    evs.append(Event(type="meal", start_time=(st - timedelta(minutes=20)).isoformat(timespec="minutes"), carbs_g=20, duration_min=5, uncertainty=0.1, source="tap", label="20 g pre-workout snack"))
                elif sn == "bedtime_15g":
                    evs.append(Event(type="meal", start_time=day.replace(hour=22, minute=30).isoformat(timespec="minutes"), carbs_g=15, duration_min=5, uncertainty=0.1, source="tap", label="15 g bedtime snack"))
                if co is not None:
                    t_drink = day.replace(hour=co - 2, minute=0)
                    evs.append(Event(type="alcohol", start_time=t_drink.isoformat(timespec="minutes"), duration_min=120, alcohol_g=14.0 * drinks, carbs_g=10.0 * drinks, uncertainty=0.25, source="tap", label=f"{drinks} drinks, last by {co}:00"))
                cands.append((st, sn, co, evs))
    if not cands:
        cands.append((day.replace(hour=7), "none", None, routine))

    # ---- batched deterministic integration of all candidate days (26 h so the night after is included)
    horizon = 26 * 60
    n_steps = horizon // DT
    ctx_past = twin.context_events(past_hours=8.0)
    inputs = np.stack([events_to_inputs(sorted(ctx_past + evs, key=lambda e: e.start), day, n_steps, DT, p) for *_, evs in cands], axis=1)
    x0 = np.repeat(hidden[None, :] if hidden is not None else fast.steady_state_init(np.array([s0.glucose]), np.array([s0.plasma_insulin]), p), len(cands), axis=0)
    x0[:, IDX["Q1"]] = s0.glucose / fast.MG_PER_MMOL * p["VG"]
    X = fast.integrate(x0, inputs, p, DT, substeps=2)
    G = fast.glucose_mgdl(X, p)                       # (T+1, B)
    E = fast.energy_score(X, p)
    day_from = 6 * 60 // DT   # the night before 06:00 is inherited, not planned
    tir = np.mean((G[day_from:] >= 70) & (G[day_from:] <= 180), axis=0)
    energy = E[day_from:].mean(axis=0)
    gmin = G[day_from:].min(axis=0)
    # deterministic proxy for the hypo constraint, then Monte Carlo on the top few
    ok = gmin > 85
    obj = tir + energy / 100.0 - 2.0 * np.maximum(85 - gmin, 0) / 30.0
    order = np.argsort(-(obj + 5.0 * ok))
    best_i, best_mc = int(order[0]), None
    for i in order[:4]:
        st, sn, co, evs = cands[int(i)]
        mc = run_monte_carlo(s0, sorted(ctx_past + evs, key=lambda e: e.start), twin.params, twin.posterior, horizon_min=horizon,
                             n=120, t0=day, hidden=hidden, seed=int(i))
        # the constraint applies to the window this decision controls: 1 h before to 5 h after the workout
        w0 = max(int((st - day).total_seconds() // 300) - 12, day_from)
        w1 = min(w0 + 12 + 60, mc.glucose_samples.shape[1])
        mc.p_hypo = float(np.mean(mc.glucose_samples[:, w0:w1].min(axis=1) < 70))
        if best_mc is None or mc.p_hypo < best_mc.p_hypo:
            best_i, best_mc = int(i), mc
        if mc.p_hypo < rules["hypo_probability_max_for_approval"]:
            break
    st, sn, co, evs = cands[best_i]
    g = G[:, best_i]
    times = [(day + timedelta(minutes=DT * k)).isoformat(timespec="minutes") for k in range(n_steps + 1)]

    # ---- timeline: hourly blocks coloured by the best candidate's forecast band
    timeline: List[TimelineBlock] = []
    for h in range(24):
        seg = g[h * 12:(h + 1) * 12 + 1]
        lo, hi = float(seg.min()), float(seg.max())
        if lo < 70 or hi > 250:
            color, label = "red", "low risk" if lo < 70 else "high"
        elif lo < 85 or hi > 180:
            color, label = "amber", "watch: near low" if lo < 85 else "above range"
        else:
            color, label = "green", "in range"
        # annotate events
        for e in evs:
            if e.start.hour == h and e.start.date() == day.date():
                label = f"{e.label or e.type} - {label}"
                break
        timeline.append(TimelineBlock(start=day.replace(hour=h).isoformat(timespec="minutes"),
                                      end=(day.replace(hour=h) + timedelta(hours=1)).isoformat(timespec="minutes"), color=color, label=label))
    notes = [f"Searched {len(cands)} candidate days ({len(starts)} workout slots x {len(snack_opts)} snack options x {len(cutoffs)} drink cutoffs)."]
    notes.append(f"Best: workout at {st.strftime('%H:%M')}, snack = {sn.replace('_', ' ')}" + (f", last drink by {co}:00" if co else "") + f"; deterministic min glucose from 06:00 {gmin[best_i]:.0f} mg/dL.")
    if best_mc is not None:
        notes.append(f"Monte Carlo on the winner (1 h before to 5 h after the workout): P(hypo) = {best_mc.p_hypo:.0%}; day TIR = {best_mc.tir:.0%}.")
    placed = [e for e in evs if e.source == "tap" or e.type in ("exercise", "alcohol")]
    return PlanResponse(date=day.date().isoformat(), timeline=timeline, energy_times=times[::6], energy_curve=[round(float(x), 1) for x in E[::6, best_i]],
                        placed_events=[EventModel(**e.to_dict()) for e in placed], workout_start=st.isoformat(timespec="minutes"),
                        snack_time=next((e.start_time for e in evs if e.source == "tap" and e.type == "meal"), None),
                        drink_cutoff=(day.replace(hour=co).isoformat(timespec="minutes") if co else None),
                        objective=round(float(obj[best_i]), 3), p_hypo=round(best_mc.p_hypo, 3) if best_mc else 0.0,
                        tir=round(float(tir[best_i]), 3), notes=notes,
                        glucose_times=list(best_mc.times) if best_mc else times, glucose_median=[round(float(x), 1) for x in (best_mc.median if best_mc else g)],
                        glucose_p10=[round(float(x), 1) for x in best_mc.p10] if best_mc else [], glucose_p90=[round(float(x), 1) for x in best_mc.p90] if best_mc else [])
