"""The Twin: one object holding the patient's data, fitted parameters,
posterior, residual model, drift status, the UKF state estimate at "now", and
the session (approved events, cards, escalations). Every route and every
decision function goes through it."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.config import DEMO_NOW, FORECAST_HORIZON_MIN, MC_SAMPLES
from backend.schema.state import State, FAST_FIELDS, MEDIUM_FIELDS, UNITS
from backend.schema.events import Event
from backend.schema.api import DriftStatus, Escalation, PermissionCard, StateNow
from backend.data.store import load_patient, PatientData
from backend.engine import fast
from backend.engine.montecarlo import run_monte_carlo, MCResult
from backend.engine.simulate import simulate, Trajectories
from backend.engine.slow import WeekProfile, DayProfile, weekly_hazard, ORGANS
from backend.inference.fitter import fitted_params, posterior as load_posterior
from backend.inference.estimator import run_ukf, UKFResult
from backend.inference.residual import load_residual_model, features_at, _slope_at, ResidualModel
from backend.inference.windows import twin_daily_states
from backend.safety.gate import GateContext, run_gate, GateDecision


class Twin:
    def __init__(self, patient_id: str = "demo", now: Optional[datetime] = None):
        self.now: datetime = now or datetime.fromisoformat(DEMO_NOW)
        self.pt: PatientData = load_patient(patient_id, until=self.now)
        self.params: Dict[str, Any] = fitted_params(self.pt)
        self.posterior: Dict[str, Dict[str, float]] = load_posterior(self.pt)
        self.residual: Optional[ResidualModel] = load_residual_model(self.pt)
        dpath = self.pt.path / "drift.json"
        self.drift_data: Dict[str, Any] = json.loads(dpath.read_text(encoding="utf-8")) if dpath.exists() else {}
        self.session_events: List[Event] = []
        self.cards: List[Dict[str, Any]] = []
        self.escalations: List[Escalation] = []
        self.last_card: Optional[PermissionCard] = None
        self._ukf: Optional[UKFResult] = None
        self._daily = twin_daily_states(self.pt)
        # the twin's own clinical carb ratio (titrated on the fitted physiology, not the hidden truth)
        try:
            self.params["carb_ratio_g_per_u"] = float(fast.calibrate_carb_ratio(self.params))
        except Exception:
            pass

    # ------------------------------------------------------------ state
    def ukf(self) -> UKFResult:
        if self._ukf is None:
            self._ukf = run_ukf(self.pt, self.params, hours=12.0, end=self.now)
        return self._ukf

    def medium_state(self) -> State:
        key = (self.now - timedelta(days=1)).date().isoformat()
        return self._daily.get(key) or (list(self._daily.values())[-1] if self._daily else State())

    def state_now(self) -> Tuple[State, Dict[str, float]]:
        u = self.ukf()
        s = u.state(template=self.medium_state())
        # slow accumulators: hazard accumulated over the observed 13 weeks
        wk = self.week_profile()
        h = weekly_hazard(wk)
        n_weeks = max(len(self.pt.daily) // 7, 1)
        for k in ORGANS:
            setattr(s, k, h[k] * n_weeks)
        std = u.std_fast()
        return s, std

    def hidden_now(self) -> np.ndarray:
        return self.ukf().mean.copy()

    def staleness_min(self, override: Optional[float] = None) -> float:
        if override is not None:
            return float(override)
        return float(self.pt.cgm.staleness_min)

    def readings_below_54_24h(self) -> int:
        """Number of distinct severe-hypo episodes (< 54 mg/dL) in the last 24 h.
        Consecutive readings form one episode; a new episode needs >= 30 min above 54."""
        t = self.pt.cgm.times
        m = (t > pd.Timestamp(self.now - timedelta(hours=24))) & (t <= pd.Timestamp(self.now))
        g = self.pt.cgm.glucose[m]
        v = self.pt.cgm.valid[m]
        low = (g < 54) & v
        episodes, last_low = 0, -100
        for i, is_low in enumerate(low):
            if is_low:
                if i - last_low > 6:
                    episodes += 1
                last_low = i
        return int(episodes)

    def drift_status(self) -> DriftStatus:
        st = self.drift_data.get("status")
        if not st:
            return DriftStatus(score=1.0, flagged=False, since=None, days_flagged=0, history=[])
        return DriftStatus(**st)

    def state_now_response(self, stale_override: Optional[float] = None) -> StateNow:
        s, std = self.state_now()
        return StateNow(values={k: round(float(v), 4) for k, v in s.to_dict().items()},
                        std={k: round(float(v), 4) for k, v in std.items()}, units=UNITS,
                        as_of=self.now.isoformat(timespec="minutes"),
                        data_quality=round(float(self.pt.cgm.data_quality), 3),
                        staleness_min=self.staleness_min(stale_override),
                        dka_flag=bool(s.ketones > 1.5 and s.glucose > 250))

    def gate_context(self, proposed_type: Optional[str] = None, stale_override: Optional[float] = None) -> GateContext:
        s, _ = self.state_now()
        return GateContext(glucose=s.glucose, ketones=s.ketones, staleness_min=self.staleness_min(stale_override),
                           data_quality=float(self.pt.cgm.data_quality), readings_below_54_24h=self.readings_below_54_24h(),
                           drift_flagged_days=self.drift_status().days_flagged, proposed_type=proposed_type)

    def gate(self, proposed_type: Optional[str] = None, stale_override: Optional[float] = None) -> GateDecision:
        d = run_gate(self.gate_context(proposed_type, stale_override))
        if d.action == "escalate":
            self.escalations.append(Escalation(reason=d.reason, instruction=d.instruction, at=self.now.isoformat(timespec="minutes")))
        return d

    # ------------------------------------------------------------ events
    def events_recent(self, hours: float = 24.0) -> List[Event]:
        lo = self.now - timedelta(hours=hours)
        return [e for e in self.pt.events if lo <= e.start <= self.now]

    def events_24h_counts(self) -> Dict[str, int]:
        return dict(Counter(e.type for e in self.events_recent(24.0)))

    def future_events(self) -> List[Event]:
        return sorted([e for e in self.session_events if e.start >= self.now - timedelta(minutes=5)], key=lambda e: e.start)

    def accept_event(self, e: Event) -> None:
        self.session_events.append(e)

    def context_events(self, extra: Optional[List[Event]] = None, past_hours: float = 8.0) -> List[Event]:
        """Events the forecast replays: recent past (for tau_g / basal overrides), accepted future, and extras."""
        ev = self.events_recent(past_hours) + self.future_events() + list(extra or [])
        return sorted(ev, key=lambda e: e.start)

    # ------------------------------------------------------------ forecasting
    def forecast(self, extra: Optional[List[Event]] = None, horizon_min: int = FORECAST_HORIZON_MIN, n: int = MC_SAMPLES,
                 apply_residual: bool = True, seed: int = 0) -> MCResult:
        s, _ = self.state_now()
        mc = run_monte_carlo(s, self.context_events(extra), self.params, self.posterior, horizon_min=horizon_min,
                             n=n, t0=self.now, hidden=self.hidden_now(), glucose_std=5.0, seed=seed)
        if apply_residual and self.residual is not None:
            corr = self.residual_curve(mc.t_min)
            mc.median = mc.median + corr
            mc.p10 = mc.p10 + corr
            mc.p90 = mc.p90 + corr
            mc.glucose_samples = mc.glucose_samples + corr[None, :]
            gmin = mc.glucose_samples.min(axis=1)
            mc.min_glucose_samples = gmin
            mc.p_hypo = float(np.mean(gmin < 70))
            mc.p_hyper = float(np.mean(mc.glucose_samples.max(axis=1) > 250))
            mc.tir = float(np.mean((mc.glucose_samples >= 70) & (mc.glucose_samples <= 180)))
        return mc

    def residual_curve(self, t_min: np.ndarray) -> np.ndarray:
        if self.residual is None:
            return np.zeros_like(t_min, dtype=float)
        s, _ = self.state_now()
        feats = features_at(self.pt, self.now, float(s.glucose), _slope_at(self.pt, self.now))
        try:
            return self.residual.correction_curve(feats, np.asarray(t_min, dtype=float))
        except Exception:
            return np.zeros_like(t_min, dtype=float)

    def deterministic(self, extra: Optional[List[Event]] = None, horizon_min: int = FORECAST_HORIZON_MIN) -> Trajectories:
        s, _ = self.state_now()
        return simulate(s, self.context_events(extra), self.params, horizon_min, t0=self.now, hidden=self.hidden_now())

    # ------------------------------------------------------------ lifestyle summaries
    def representative_week_events(self) -> Tuple[datetime, List[Event]]:
        """Events of the last complete Monday-Sunday week before now."""
        monday = (self.now - timedelta(days=self.now.weekday())).replace(hour=0, minute=0)
        start = monday - timedelta(days=7)
        end = monday
        ev = [e for e in self.pt.events if start <= e.start < end]
        return start, ev

    def week_profile(self, weeks: int = 4) -> WeekProfile:
        """Per-weekday averages over the last `weeks` weeks of observed data."""
        frame = self.pt.cgm.to_frame()
        frame = frame[frame["valid"] & (frame["time"] <= pd.Timestamp(self.now))]
        frame = frame[frame["time"] > pd.Timestamp(self.now - timedelta(days=7 * weeks))]
        frame["date"] = frame["time"].dt.date
        frame["wd"] = frame["time"].dt.weekday
        alc: Dict[int, List[float]] = {i: [] for i in range(7)}
        for e in self.pt.events:
            if e.type == "alcohol" and self.now - timedelta(days=7 * weeks) <= e.start <= self.now:
                alc[e.start.weekday()].append(e.alcohol_g)
        days = []
        ms = self.medium_state()
        for wd in range(7):
            sub = frame[frame["wd"] == wd]
            g = sub["glucose"].to_numpy()
            if len(g) < 12:
                g = frame["glucose"].to_numpy()
            n_days = max(len(set(sub["date"])), 1)
            days.append(DayProfile(
                mean_glucose=float(np.mean(g)), sd_glucose=float(np.std(g)),
                frac_above_180=float(np.mean(g > 180)),
                hydration=float(0.9 - 0.15 * np.mean(g > 180) - 0.05 * (sum(alc[wd]) / n_days) / 50.0),
                alcohol_g=float(sum(alc[wd]) / n_days), sleep_debt=float(ms.sleep_debt), fat_mass=float(ms.fat_mass),
                hypo_minutes=float(np.mean(g < 70) * 1440), tir=float(np.mean((g >= 70) & (g <= 180)))))
        return WeekProfile(days)

    # ------------------------------------------------------------ session cards
    def remember_card(self, card: PermissionCard, kind: str = "permission") -> None:
        self.last_card = card
        self.cards.append({"kind": kind, "at": self.now.isoformat(timespec="minutes"), "card": card.model_dump()})


_TWIN: Optional[Twin] = None


def get_twin() -> Twin:
    global _TWIN
    if _TWIN is None:
        _TWIN = Twin()
    return _TWIN


def reset_twin() -> Twin:
    global _TWIN
    _TWIN = Twin()
    return _TWIN
