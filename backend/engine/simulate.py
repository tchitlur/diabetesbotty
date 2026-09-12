"""STUB simulator (checkpoint 1). Replaced with the Hovorka model in checkpoint 2.

Returns a plausible fake curve so the API and frontend can be built against
the real Trajectories contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from backend.schema.state import State, ALL_FIELDS
from backend.schema.events import Event


@dataclass
class Trajectories:
    t_min: np.ndarray
    series: Dict[str, np.ndarray]
    min_glucose: float = 0.0
    max_glucose: float = 0.0
    tir: float = 0.0
    hypo_minutes: float = 0.0
    hyper_minutes: float = 0.0
    flags: Dict[str, bool] = field(default_factory=dict)

    def final_state(self) -> State:
        s = State()
        for k in ALL_FIELDS:
            if k in self.series:
                setattr(s, k, float(self.series[k][-1]))
        return s

    def summarize(self) -> None:
        g = self.series["glucose"]
        self.min_glucose = float(np.min(g))
        self.max_glucose = float(np.max(g))
        n = len(g)
        self.tir = float(np.mean((g >= 70) & (g <= 180))) if n else 0.0
        dt = float(self.t_min[1] - self.t_min[0]) if n > 1 else 5.0
        self.hypo_minutes = float(np.sum(g < 70) * dt)
        self.hyper_minutes = float(np.sum(g > 250) * dt)


def simulate(state: State, events: List[Event], params: dict, horizon_min: int, dt_min: int = 5) -> Trajectories:
    n = int(horizon_min // dt_min) + 1
    t = np.arange(n) * dt_min
    g = state.glucose + 15 * np.sin(t / 90.0) - 0.02 * t
    series = {k: np.full(n, float(getattr(state, k))) for k in ALL_FIELDS}
    series["glucose"] = g
    traj = Trajectories(t_min=t, series=series)
    traj.summarize()
    return traj
