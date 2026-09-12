from datetime import datetime, timedelta

from backend.schema.events import Event
from backend.decision.permission import build_variants, _halve
from backend.decision.change import rewrite_week, CHANGES
from backend.decision.replay import modify_events


def test_variants_cover_spec():
    e = Event(type="exercise", start_time="2025-08-30T07:00", duration_min=30, exercise_kind="aerobic", intensity=0.6)
    names = [n for n, _, _ in build_variants(e)]
    assert {"delay_1h", "halve", "pre_workout_snack_20g", "fast_carbs_15g"} <= set(names)
    a = Event(type="alcohol", start_time="2025-08-29T21:00", alcohol_g=28, carbs_g=26)
    names = [n for n, _, _ in build_variants(a)]
    assert "fast_carbs_15g" in names and "halve" in names
    assert _halve(a).alcohol_g == 14


def test_rewrite_week_changes():
    ws = datetime(2025, 8, 18)
    ev = [Event(type="exercise", start_time="2025-08-19T17:30", duration_min=45, exercise_kind="aerobic"),
          Event(type="caffeine", start_time="2025-08-19T08:00", caffeine_mg=120),
          Event(type="alcohol", start_time="2025-08-23T21:00", alcohol_g=56, carbs_g=52),
          Event(type="meal", start_time="2025-08-19T07:30", carbs_g=40),
          Event(type="insulin", start_time="2025-08-19T07:30", insulin_units=3, insulin_kind="bolus"),
          Event(type="sleep", start_time="2025-08-18T23:00", sleep_hours=6.5)]
    mw = rewrite_week("morning_workouts", ws, ev)
    ex = [e for e in mw if e.type == "exercise"]
    assert len(ex) == 3 and all(e.start.hour == 7 for e in ex)
    assert not any(e.type == "caffeine" for e in rewrite_week("cut_caffeine", ws, ev))
    assert not any(e.type == "alcohol" for e in rewrite_week("drink_fridays_only", ws, ev))  # the Saturday drink goes
    f = rewrite_week("fasting_16_8", ws, ev)
    assert not any(e.type == "meal" and e.start.hour < 12 for e in f)
    assert not any(e.type == "insulin" and e.insulin_kind == "bolus" for e in f)
    assert len(rewrite_week("no_change", ws, ev)) == len(ev)
    assert "no_change" in CHANGES


def test_modify_events_scales():
    ev = [Event(type="alcohol", start_time="2025-08-22T21:00", alcohol_g=42, carbs_g=39),
          Event(type="meal", start_time="2025-08-22T19:00", carbs_g=60)]
    out = modify_events(ev, carbs_scale=0.5, alcohol_scale=0.0)
    assert len(out) == 1 and out[0].carbs_g == 30
