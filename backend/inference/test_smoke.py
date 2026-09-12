import numpy as np

from backend.config import DEMO_PATIENT_DIR
from backend.data.store import load_patient
from backend.inference.windows import build_windows, pick_starts, batch_params, run_batch
from backend.inference.fitter import Fitter, fitted_params
from backend.inference.estimator import run_ukf
from backend.inference.residual import ResidualModel, build_dataset, FEATURES
from backend.inference.drift import drift_status_from_log


def _pt():
    assert (DEMO_PATIENT_DIR / "cgm.csv").exists(), "run: python -m backend.data.cohort --demo-only"
    return load_patient("demo")


def test_windows_and_batch_run():
    pt = _pt()
    p = fitted_params(pt)
    rng = np.random.default_rng(0)
    starts = pick_starts(pt, 5, 8, per_day=[7, 19], rng=rng)
    wb = build_windows(pt, starts, p, warmup_min=60, horizon_min=120)
    G = run_batch(wb, batch_params(p, {}, wb))
    assert G.shape == (wb.B, 25)
    assert np.all(np.isfinite(G))


def test_fitter_few_iterations_moves_params():
    pt = _pt()
    f = Fitter(pt, n_windows=8, seed=1)
    out = f.fit(max_nfev=3, verbose=False)
    assert out["rmse_train_mgdl"] < 60
    assert set(out["params"]) >= {"si_tod0", "carb_ratio", "alcohol_gain", "sleep_debt_coef"}
    assert all(v["std"] > 0 for v in out["params"].values())


def test_ukf_runs_fast_and_tracks():
    pt = _pt()
    p = fitted_params(pt)
    r = run_ukf(pt, p, hours=3)
    assert r.innovation_rmse < 40
    sd = r.std_fast()
    assert sd["glucose"] > 0
    s = r.state()
    assert 30 < s.glucose < 450


def test_residual_model_fits():
    pt = _pt()
    p = fitted_params(pt)
    rng = np.random.default_rng(2)
    starts = pick_starts(pt, 2, 6, per_day=[6, 12, 18], rng=rng)
    X, err, _ = build_dataset(pt, p, starts)
    assert list(X.columns) == FEATURES
    m = ResidualModel()
    m.fit(X, err)
    curve = m.correction_curve(X.iloc[0].to_dict(), np.arange(0, 481, 5))
    assert curve[0] == 0.0 and curve[-1] == 0.0


def test_drift_flag_logic():
    flat = [{"date": f"2025-08-{d:02d}", "rmse_combined_60": 12.0, "rmse_ode_60": 13.0} for d in range(1, 11)]
    assert not drift_status_from_log(flat).flagged
    rising = flat + [{"date": f"2025-08-{d:02d}", "rmse_combined_60": 12.0 + 3 * (d - 10), "rmse_ode_60": 13.0} for d in range(11, 16)]
    st = drift_status_from_log(rising)
    assert st.flagged and st.since is not None and st.score > 1.0
