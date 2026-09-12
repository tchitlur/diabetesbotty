"""Alerts: if the do-nothing forecast crosses < 70 or > 250, emit an Alert
with the window and the past event most responsible (largest sensitivity:
re-simulate the last 12 h with each recent event removed, batched)."""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

import numpy as np

from backend.schema.events import Event
from backend.schema.state import State
from backend.schema.api import Alert, EventModel
from backend.engine import fast
from backend.engine.fast import IDX, NU
from backend.engine.simulate import events_to_inputs, initial_vector, state_params
from backend.inference.windows import observed_at

PROB_THRESHOLD = 0.15


def _window(prob: np.ndarray, times: List[str]):
    idx = np.where(prob >= PROB_THRESHOLD)[0]
    if len(idx) == 0:
        return None
    return times[idx[0]], times[idx[-1]], float(prob.max())


def cause_event(twin, kind: str, horizon_min: int) -> Optional[Event]:
    """Which past event (last 12 h) moves the future extreme the most when removed?"""
    past = [e for e in twin.events_recent(12.0) if e.type in ("meal", "insulin", "alcohol", "exercise", "caffeine")
            and not (e.type == "insulin" and e.insulin_kind == "basal")]
    if not past:
        return None
    t_warm = twin.now - timedelta(hours=12)
    g_warm = observed_at(twin.pt, t_warm) or 120.0
    p = state_params(twin.medium_state(), twin.params)
    s0 = State(glucose=g_warm, plasma_insulin=float(fast.steady_basal_insulin(p, max(g_warm, 70.0))), liver_glycogen=60.0)
    n_steps = (12 * 60 + horizon_min) // 5
    future_from = 12 * 60 // 5
    base_events = twin.context_events(past_hours=20.0)
    sets = [base_events] + [[x for x in base_events if x is not e] for e in past]
    inputs = np.stack([events_to_inputs(evs, t_warm, n_steps, 5, p) for evs in sets], axis=1)  # (T, B, NU)
    x0 = np.repeat(initial_vector(s0, p), len(sets), axis=0)
    X = fast.integrate(x0, inputs, p, 5, substeps=2)
    G = fast.glucose_mgdl(X[future_from:], p)     # (H+1, B)
    if kind == "hypo":
        ext = G.min(axis=0)
        delta = ext[1:] - ext[0]          # removing the cause raises the minimum
    else:
        ext = G.max(axis=0)
        delta = ext[0] - ext[1:]          # removing the cause lowers the maximum
    i = int(np.argmax(delta))
    return past[i] if delta[i] > 3.0 else None


def compute_alerts(twin, horizon_min: int = 480) -> List[Alert]:
    mc = twin.forecast(extra=None, horizon_min=horizon_min)
    G = mc.glucose_samples
    out: List[Alert] = []
    p_low = np.mean(G < 70, axis=0)
    p_high = np.mean(G > 250, axis=0)
    w = _window(p_low, mc.times)
    if w:
        c = cause_event(twin, "hypo", horizon_min)
        out.append(Alert(window_start=w[0], window_end=w[1], kind="hypo", probability=round(w[2], 3),
                         cause_event=EventModel(**c.to_dict()) if c else None,
                         message=f"Glucose likely below 70 mg/dL between {w[0][11:16]} and {w[1][11:16]} (peak probability {w[2]:.0%})." + (f" Most responsible past event: {c.label or c.type} at {c.start_time[11:16]}." if c else "")))
    w = _window(p_high, mc.times)
    if w:
        c = cause_event(twin, "hyper", horizon_min)
        out.append(Alert(window_start=w[0], window_end=w[1], kind="hyper", probability=round(w[2], 3),
                         cause_event=EventModel(**c.to_dict()) if c else None,
                         message=f"Glucose likely above 250 mg/dL between {w[0][11:16]} and {w[1][11:16]} (peak probability {w[2]:.0%})." + (f" Most responsible past event: {c.label or c.type} at {c.start_time[11:16]}." if c else "")))
    if mc.p_dka > 0.05:
        out.append(Alert(window_start=mc.times[0], window_end=mc.times[-1], kind="dka", probability=round(mc.p_dka, 3),
                         message="Ketones rising with high glucose: check ketones."))
    return out
