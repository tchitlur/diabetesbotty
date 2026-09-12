import numpy as np

from backend.config import DEMO_PATIENT_DIR
from backend.data.cohort import sample_patient, generate_events, START, N_DAYS
from backend.data.store import load_patient
from backend.schema.events import EVENT_TYPES


def test_sample_patient_and_events_are_valid():
    rng = np.random.default_rng(0)
    meta = sample_patient(rng, 5)
    assert 50 <= meta["body_weight_kg"] <= 100
    assert meta["true_params"]["basal_u_per_h"] > 0
    assert 3 < meta["true_params"]["carb_ratio_g_per_u"] < 80
    true_ev, logged_ev = generate_events(meta, np.random.default_rng(1))
    assert len(true_ev) == len(logged_ev) > 90 * 5
    assert all(e.type in EVENT_TYPES for e in true_ev)
    meals_t = [e for e in true_ev if e.type == "meal"]
    meals_l = [e for e in logged_ev if e.type == "meal"]
    ratio = np.array([l.carbs_g / t.carbs_g for t, l in zip(meals_t, meals_l)])
    assert 0.2 < ratio.std() < 0.4          # ~30 % logging error
    assert any(e.type == "alcohol" for e in true_ev)
    assert any(e.type == "exercise" for e in true_ev)


def test_demo_patient_loads():
    assert (DEMO_PATIENT_DIR / "cgm.csv").exists(), "run: python -m backend.data.cohort --demo-only"
    pt = load_patient("demo")
    assert pt.cgm.data_quality > 0.5
    assert len(pt.events) > 500
    assert len(pt.daily) == N_DAYS
    assert pt.now.date() >= (START.date())
