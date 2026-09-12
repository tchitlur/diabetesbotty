import time

import numpy as np

from backend.schema.state import State
from backend.schema.events import Event
from backend.engine import fast
from backend.engine.params import build_params
from backend.engine.simulate import simulate
from backend.engine.montecarlo import run_monte_carlo


def _patient():
    p = build_params()
    I0 = fast.steady_basal_insulin(p)
    return p, State(glucose=120, plasma_insulin=I0, liver_glycogen=60)


def test_simulate_shape_and_steady_state():
    p, st = _patient()
    tr = simulate(st, [], p, horizon_min=480, t0="2025-03-07T08:00")
    assert len(tr.t_min) == 97
    g = tr.series["glucose"]
    assert abs(g[-1] - 120) < 30  # no events: stays roughly where it started
    assert tr.max_glucose >= tr.min_glucose
    assert all(k in tr.series for k in ("ketones", "hydration", "energy_score", "blood_alcohol"))


def test_meal_raises_and_bolus_lowers():
    p, st = _patient()
    t0 = "2025-03-07T08:00"
    meal = [Event(type="meal", start_time=t0, carbs_g=60)]
    tr_m = simulate(st, meal, p, 240, t0=t0)
    assert tr_m.max_glucose > 160
    bolus = meal + [Event(type="insulin", start_time=t0, insulin_units=60 / 30.0, insulin_kind="bolus")]
    tr_b = simulate(st, bolus, p, 240, t0=t0)
    assert tr_b.series["glucose"][-1] < tr_m.series["glucose"][-1]


def test_alcohol_delayed_low():
    p, st = _patient()
    st.glucose = 130
    t0 = "2025-03-07T21:00"
    ev = [Event(type="alcohol", start_time=t0, duration_min=120, alcohol_g=56, carbs_g=48)]
    tr = simulate(st, ev, p, 12 * 60, t0=t0)
    i = int(np.argmin(tr.series["glucose"]))
    t_nadir_h = tr.t_min[i] / 60.0
    assert tr.min_glucose < 70
    assert 4.0 <= t_nadir_h <= 10.5


def test_exercise_lowers_glucose():
    p, st = _patient()
    t0 = "2025-03-07T08:00"
    ev = [Event(type="exercise", start_time="2025-03-07T09:00", duration_min=30, exercise_kind="aerobic", intensity=0.6)]
    tr = simulate(st, ev, p, 240, t0=t0)
    tr0 = simulate(st, [], p, 240, t0=t0)
    assert tr.series["glucose"][-1] < tr0.series["glucose"][-1] - 10


def test_rk4_matches_solve_ivp():
    p, st = _patient()
    t0 = "2025-03-07T08:00"
    ev = [Event(type="meal", start_time=t0, carbs_g=40)]
    a = simulate(st, ev, p, 120, t0=t0)
    b = simulate(st, ev, p, 120, t0=t0, method="solve_ivp")
    assert np.max(np.abs(a.series["glucose"] - b.series["glucose"])) < 0.5


def test_monte_carlo_under_two_seconds():
    p, st = _patient()
    ev = [Event(type="alcohol", start_time="2025-03-07T21:00", duration_min=120, alcohol_g=56, carbs_g=48)]
    tic = time.time()
    mc = run_monte_carlo(st, ev, p, {}, horizon_min=480, n=200, t0="2025-03-07T21:00")
    assert time.time() - tic < 2.0
    assert len(mc.median) == 97
    assert 0.0 <= mc.p_hypo <= 1.0
    assert np.all(mc.p10 <= mc.p90 + 1e-9)


def test_medium_layer_sleep_and_a1c():
    from backend.engine.medium import daily_update, DaySummary, hba1c_steady_state
    s = State(hba1c=7.0)
    poor = daily_update(s, DaySummary(mean_glucose=154, sleep_hours=5.0))
    assert poor.sleep_debt > 2.0
    good = daily_update(poor, DaySummary(mean_glucose=154, sleep_hours=8.5))
    assert good.sleep_debt < poor.sleep_debt
    assert abs(hba1c_steady_state(154.0) - 7.0) < 0.05
    # 120 days at 212 mg/dL (A1c 9 by ADAG) should move A1c most of the way there
    for _ in range(120):
        s = daily_update(s, DaySummary(mean_glucose=212, sleep_hours=7.5))
    assert s.hba1c > 8.3


def test_slow_layer_dcct():
    from backend.engine.slow import dcct_check, run_slow, constant_week
    r = dcct_check()
    assert 70 <= r["reduction_pct"] <= 80
    res = run_slow(constant_week(150, 40, alcohol_g=30), State())
    assert all(0.0 < v < 1.0 for v in res.probabilities.values())
    assert res.final_state.dmg_liver > 0
