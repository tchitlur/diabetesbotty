"""Synthetic cohort generator.

30 virtual Type 1 patients, each with Hovorka parameters sampled from the
published ranges in params.yaml, 90 days of realistic events, the *true*
model run day by day (all patients batched through the vectorised RK4), CGM
noise (AR(1) sensor error, rho 0.7, sd 6 mg/dL; 5 % dropouts; compression lows), and +-30 % error on the
logged meal carbs.

Usage:
    python -m backend.data.cohort               # full cohort (30) + demo patient
    python -m backend.data.cohort --demo-only   # just the committed demo patient
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from backend.config import COHORT_DIR, DEMO_PATIENT_DIR, DATA_DIR
from backend.schema.state import State, MEDIUM_FIELDS
from backend.schema.events import Event
from backend.engine import fast
from backend.engine.fast import IDX, NS, NU
from backend.engine.params import build_params, cohort_ranges, load_yaml
from backend.engine.simulate import events_to_inputs, initial_vector
from backend.engine.medium import daily_update, summarize_day
from backend.adapters.csv_ingest import write_dexcom_csv, ingest_csv

N_PATIENTS = 30
N_DAYS = 90
START = datetime(2025, 6, 2, 0, 0)   # a Monday
DT = 5
STEPS_PER_DAY = 24 * 60 // DT
DEMO_INDEX = 0
COHORT_SEED = 2026


# ------------------------------------------------------------------ patients

def sample_patient(rng: np.random.Generator, idx: int) -> Dict[str, Any]:
    r = cohort_ranges()
    over: Dict[str, Any] = {}
    # insulin sensitivities share a common per-patient factor (they co-vary in people;
    # sampling them independently produces impossible physiologies) plus small own noise
    common = float(np.clip(np.exp(rng.normal(0.0, 0.30)), 0.55, 1.8))
    for k in ("SIT", "SID", "SIE", "k12", "ke", "EGP0", "F01", "tmaxG", "tmaxI"):
        m, cv = r[k]["mean"], r[k]["cv"]
        if k in ("SIT", "SID", "SIE"):
            own = float(np.clip(np.exp(rng.normal(0.0, 0.12)), 0.75, 1.3))
            over[k] = float(m * common * own)
        else:
            sigma = np.sqrt(np.log(1 + cv ** 2))
            over[k] = float(m * np.clip(np.exp(rng.normal(-0.5 * sigma ** 2, sigma)), 0.7, 1.4))
    over["AG"] = float(rng.uniform(r["AG"]["min"], r["AG"]["max"]))
    over["carb_ratio"] = over["AG"]
    over["tau_carb"] = over["tmaxG"]
    bw = float(rng.uniform(r["body_weight_kg"]["min"], r["body_weight_kg"]["max"]))
    over["BW"] = bw
    sex = "F" if rng.random() < 0.5 else "M"
    over["alcohol_widmark_r"] = 0.55 if sex == "F" else 0.68
    over["alcohol_gain"] = float(rng.uniform(r["alcohol_gain"]["min"], r["alcohol_gain"]["max"]))
    over["exercise_mult"] = float(rng.uniform(r["exercise_mult"]["min"], r["exercise_mult"]["max"]))
    dawn = float(rng.normal(1.0, 0.08))
    over["si_tod0"] = float(np.clip(0.85 * dawn, 0.6, 1.2))
    over["si_tod1"] = 1.0
    over["si_tod2"] = float(np.clip(1.1 * rng.normal(1.0, 0.06), 0.8, 1.4))
    over["sleep_debt_coef"] = float(rng.uniform(0.1, 0.3))
    over["basal_drift"] = 1.0
    p = build_params(over)
    steady = fast.steady_basal_rate(p, 130.0)
    dose_err = float(rng.uniform(r["basal_dose_error"]["min"], r["basal_dose_error"]["max"]))
    over["basal_u_per_h"] = float(steady * dose_err)
    over["carb_ratio_g_per_u"] = float(fast.calibrate_carb_ratio(p))
    fat_frac = float(rng.uniform(0.15, 0.32))
    meta = {
        "patient_id": f"p{idx:02d}",
        "sex": sex,
        "body_weight_kg": bw,
        "fat_mass_kg": bw * fat_frac,
        "lean_mass_kg": bw * (1 - fat_frac),
        "basal_dose_error": dose_err,
        "steady_basal_u_per_h": steady,
        "alcohol_prob_weekend": 0.6 if idx == DEMO_INDEX else 0.3,
        "workouts_per_week": int(rng.integers(2, 5)),
        "coffee_prob": float(rng.uniform(0.6, 0.95)),
        "illness_week": int(rng.integers(2, 11)) if rng.random() < 0.4 or idx == DEMO_INDEX else -1,
        "bolus_scale": 1.0,
        "true_params": over,
        "start": START.isoformat(),
        "days": N_DAYS,
    }
    return meta


# ------------------------------------------------------------------ events

DRINK_KINDS = {"beer": (14.0, 13.0), "wine": (14.0, 4.0), "spirit": (14.0, 0.0)}


def generate_events(meta: Dict[str, Any], rng: np.random.Generator) -> Tuple[List[Event], List[Event]]:
    """Return (true_events, logged_events). Logged = true with +-30 % carb error on meals."""
    cr = meta["true_params"]["carb_ratio_g_per_u"]
    basal = meta["true_params"]["basal_u_per_h"]
    true_ev: List[Event] = []
    logged_ev: List[Event] = []
    workouts_per_week = meta["workouts_per_week"]
    illness_week = meta["illness_week"]

    def add(e_true: Event, e_logged: Event | None = None) -> None:
        true_ev.append(e_true)
        logged_ev.append(e_logged if e_logged is not None else e_true)

    for d in range(N_DAYS):
        day = START + timedelta(days=d)
        wd = day.weekday()  # 0 = Monday
        week = d // 7
        # --- workouts for this week (decided on Mondays)
        if wd == 0:
            wk_days = sorted(rng.choice(7, size=workouts_per_week, replace=False).tolist())
            workout_days = set(wk_days)
            stress_day = int(rng.integers(0, 5))
        # --- sleep (previous night, logged at bedtime of previous day)
        sleep_h = float(np.clip(rng.normal(7.2, 0.7), 6.0, 8.5))
        if wd in (5, 6):
            sleep_h = float(np.clip(sleep_h + rng.normal(0.4, 0.3), 6.0, 8.5))
        bedtime = day - timedelta(hours=1) + timedelta(minutes=int(rng.integers(-30, 31)))   # 22:30-23:30
        add(Event(type="sleep", start_time=bedtime.isoformat(timespec="minutes"), duration_min=sleep_h * 60, sleep_hours=sleep_h, source="synthetic", label="sleep"))
        wake = bedtime + timedelta(hours=sleep_h)
        # --- basal (informational: the pump/long-acting setting; total units over the day)
        add(Event(type="insulin", start_time=day.isoformat(timespec="minutes"), duration_min=1440, insulin_units=basal * 24, insulin_kind="basal", source="synthetic", label="basal"))
        # --- caffeine
        if rng.random() < meta["coffee_prob"]:   # coffee is a morning thing: 15-60 min after waking
            t = wake + timedelta(minutes=int(rng.integers(15, 60)))
            mg = float(rng.choice([80, 120, 160, 200]))
            add(Event(type="caffeine", start_time=t.isoformat(timespec="minutes"), caffeine_mg=mg, source="synthetic", label="coffee"))
        # --- meals + boluses
        meals = []
        jitter = lambda: timedelta(minutes=int(rng.integers(-30, 31)))   # meals at about 8:00 / 12:30 / 18:30, +-30 min
        if rng.random() > 0.10:
            meals.append(("breakfast", max(day.replace(hour=8, minute=0) + jitter(), wake + timedelta(minutes=15)), rng.uniform(30, 60), rng.uniform(8, 20), rng.uniform(10, 25), rng.uniform(2, 6)))
        meals.append(("lunch", day.replace(hour=12, minute=30) + jitter(), rng.uniform(45, 90), rng.uniform(10, 30), rng.uniform(20, 40), rng.uniform(3, 8)))
        meals.append(("dinner", day.replace(hour=18, minute=30) + jitter(), rng.uniform(50, 100), rng.uniform(15, 35), rng.uniform(25, 45), rng.uniform(3, 8)))
        if rng.random() < 0.3:
            snack_t = day.replace(hour=15 if rng.random() < 0.5 else 21, minute=int(rng.integers(0, 59)))
            meals.append(("snack", snack_t, rng.uniform(20, 40), rng.uniform(3, 15), rng.uniform(2, 10), rng.uniform(0, 3)))
        for name, t, carbs, fat, prot, fib in meals:
            true_meal = Event(type="meal", start_time=t.isoformat(timespec="minutes"), duration_min=15, carbs_g=float(carbs), fat_g=float(fat), protein_g=float(prot), fiber_g=float(fib), uncertainty=0.3, source="synthetic", label=name)
            logged_carbs = float(max(5.0, carbs * (1 + rng.normal(0, 0.3))))
            logged_meal = true_meal.copy(carbs_g=logged_carbs)
            add(true_meal, logged_meal)
            bolused = name != "snack" or rng.random() < 0.5
            if bolused:
                units = float(max(0.2, logged_carbs / cr * meta.get("bolus_scale", 1.0) * (1 + rng.normal(0, 0.2))))
                bt = t - timedelta(minutes=10)   # bolus 10 minutes before the meal
                add(Event(type="insulin", start_time=bt.isoformat(timespec="minutes"), insulin_units=units, insulin_kind="bolus", uncertainty=0.05, source="synthetic", label=f"bolus for {name}"))
        # --- exercise
        if wd in workout_days:
            kind = str(rng.choice(["aerobic", "aerobic", "aerobic", "anaerobic", "anaerobic", "mixed"]))
            t = day.replace(hour=7, minute=0) if rng.random() < 0.35 else day.replace(hour=17, minute=30)   # morning or after work
            dur = float(rng.choice([30, 40, 45, 60]))
            inten = float(rng.uniform(0.5, 0.8))
            if rng.random() < 0.4:
                snack = Event(type="meal", start_time=(t - timedelta(minutes=20)).isoformat(timespec="minutes"), duration_min=5, carbs_g=float(rng.uniform(15, 20)), uncertainty=0.2, source="synthetic", label="pre-workout snack")
                add(snack, snack.copy(carbs_g=float(max(5.0, snack.carbs_g * (1 + rng.normal(0, 0.3))))))
            add(Event(type="exercise", start_time=t.isoformat(timespec="minutes"), duration_min=dur, exercise_kind=kind, intensity=inten, uncertainty=0.15, source="synthetic", label=f"{kind} {int(dur)} min"))
        # --- alcohol on Fri/Sat nights
        if wd in (4, 5) and rng.random() < meta["alcohol_prob_weekend"]:
            n = int(rng.integers(2, 7))
            kind = str(rng.choice(["beer", "beer", "wine", "spirit"]))
            alc_per, carb_per = DRINK_KINDS[kind]
            t = day.replace(hour=int(rng.integers(20, 23)), minute=int(rng.integers(0, 59)))
            dur = float(min(60 + 30 * n, 240))
            add(Event(type="alcohol", start_time=t.isoformat(timespec="minutes"), duration_min=dur, alcohol_g=alc_per * n, carbs_g=carb_per * n, uncertainty=0.25, source="synthetic", label=f"{n} {kind}s"))
        # --- illness week
        if illness_week >= 0 and week == illness_week and wd == 0:
            add(Event(type="illness", start_time=day.replace(hour=6).isoformat(timespec="minutes"), duration_min=5 * 1440, severity=float(rng.uniform(0.5, 0.8)), source="synthetic", label="illness"))
        # --- one stress day per week
        if wd == stress_day:
            add(Event(type="stress", start_time=day.replace(hour=9).isoformat(timespec="minutes"), duration_min=600, severity=float(rng.uniform(0.4, 0.8)), source="synthetic", label="stressful day"))
        # --- water
        for _ in range(int(rng.integers(2, 5))):
            t = day.replace(hour=int(rng.integers(8, 22)), minute=int(rng.integers(0, 59)))
            add(Event(type="water", start_time=t.isoformat(timespec="minutes"), water_ml=float(rng.choice([250, 300, 500])), source="synthetic", label="water"))
    key = lambda e: e.start
    return sorted(true_ev, key=key), sorted(logged_ev, key=key)


# ------------------------------------------------------------------ simulation

def simulate_cohort(metas: List[Dict[str, Any]], events_true: List[List[Event]], verbose: bool = True):
    """Run the true model for all patients, batched. Returns (glucose (B, T), daily states per patient, fast series)."""
    B = len(metas)
    params = [build_params(m["true_params"]) for m in metas]
    pb: Dict[str, Any] = {}
    for k in params[0]:
        vals = [p[k] for p in params]
        if all(isinstance(v, (int, float, np.floating)) for v in vals) and len(set(map(float, vals))) > 1:
            pb[k] = np.array(vals, dtype=float)
        else:
            pb[k] = params[0][k]
    states = [State(glucose=120.0, plasma_insulin=fast.steady_basal_insulin(p), liver_glycogen=60.0,
                    fat_mass=m["fat_mass_kg"], lean_mass=m["lean_mass_kg"], hba1c=7.2)
              for p, m in zip(params, metas)]
    x = np.concatenate([initial_vector(s, p) for s, p in zip(states, params)], axis=0)  # (B, NS)
    T = N_DAYS * STEPS_PER_DAY
    G = np.zeros((B, T))
    K = np.zeros((B, T))
    daily_rows: List[List[Dict[str, Any]]] = [[] for _ in range(B)]
    ev_by_day = [[[] for _ in range(N_DAYS + 1)] for _ in range(B)]
    for i, evs in enumerate(events_true):
        for e in evs:
            d = (e.start - START).days
            if 0 <= d < N_DAYS:
                ev_by_day[i][d].append(e)
    tic = time.time()
    for d in range(N_DAYS):
        t0 = START + timedelta(days=d)
        inputs = np.zeros((STEPS_PER_DAY, B, NU))
        for i in range(B):
            window = ev_by_day[i][d - 1] + ev_by_day[i][d] if d > 0 else ev_by_day[i][d]
            inputs[:, i, :] = events_to_inputs(window, t0, STEPS_PER_DAY, DT, params[i])
        pb["insulin_sensitivity"] = np.array([s.insulin_sensitivity * (1 - params[i]["sleep_debt_coef"] * min(s.sleep_debt, 3.0) / 2.5) for i, s in enumerate(states)])
        pb["insulin_sensitivity"] = np.maximum(pb["insulin_sensitivity"], 0.3)
        pb["sleep_debt"] = np.array([s.sleep_debt for s in states])
        X = fast.integrate(x, inputs, pb, DT, substeps=2)
        x = X[-1]
        g = fast.glucose_mgdl(X[1:], pb).T  # (B, steps)
        G[:, d * STEPS_PER_DAY:(d + 1) * STEPS_PER_DAY] = g
        K[:, d * STEPS_PER_DAY:(d + 1) * STEPS_PER_DAY] = X[1:, :, IDX["K"]].T
        for i in range(B):
            summ = summarize_day(ev_by_day[i][d], float(np.mean(g[i])), float(np.std(g[i])))
            states[i] = daily_update(states[i], summ, sleep_debt_coef=params[i]["sleep_debt_coef"])
            row = {"date": t0.date().isoformat(), "mean_glucose": float(np.mean(g[i])), "sd_glucose": float(np.std(g[i])),
                   "tir": float(np.mean((g[i] >= 70) & (g[i] <= 180))), "min_glucose": float(np.min(g[i])),
                   "sleep_hours": summ.sleep_hours}
            row.update({k: float(getattr(states[i], k)) for k in MEDIUM_FIELDS})
            daily_rows[i].append(row)
        if verbose and (d + 1) % 15 == 0:
            print(f"  day {d + 1}/{N_DAYS}  ({time.time() - tic:.1f} s)")
    return G, daily_rows, K


CGM_NOISE_SD = 6.0     # mg/dL, marginal sd of the sensor error
CGM_NOISE_RHO = 0.7    # lag-1 autocorrelation of the sensor error (5-min samples): real CGM error is smooth, not white


def sensor_noise(n: int, rng: np.random.Generator, sd: float = CGM_NOISE_SD, rho: float = CGM_NOISE_RHO) -> np.ndarray:
    """AR(1) sensor error with marginal sd `sd` and lag-1 correlation `rho`."""
    e = np.empty(n)
    e[0] = rng.normal(0, sd)
    innov = rng.normal(0, sd * np.sqrt(1 - rho ** 2), size=n)
    for i in range(1, n):
        e[i] = rho * e[i - 1] + innov[i]
    return e


def add_cgm_noise(g_true: np.ndarray, rng: np.random.Generator, protect_from: int | None = None) -> np.ndarray:
    """Sensor error plus dropouts, warm-up gaps and compression lows. Indices >= protect_from
    keep the noise but get no dropouts or artifacts (the demo person's recent day stays clean)."""
    g = g_true + sensor_noise(len(g_true), rng)
    n = len(g)
    lim = n if protect_from is None else int(protect_from)
    # 5 % dropouts in short runs
    n_drop = int(0.05 * n)
    dropped = 0
    while dropped < n_drop:
        a = int(rng.integers(0, n))
        ln = int(rng.integers(1, 7))
        if a + ln > lim:
            continue
        g[a:a + ln] = np.nan
        dropped += ln
    # sensor warm-up gaps every 10 days (2 h)
    for start_day in range(10, N_DAYS, 10):
        a = start_day * STEPS_PER_DAY + int(rng.integers(0, 60))
        if a + 24 <= lim:
            g[a:a + 24] = np.nan
    # compression lows: ~1 per 5 nights, 20-40 min, -30..-50 mg/dL, ramping in and out (half-sine) like a real one
    for d in range(N_DAYS):
        if rng.random() < 0.2:
            a = d * STEPS_PER_DAY + int(rng.integers(12, 60))  # 01:00-05:00
            ln = int(rng.integers(4, 9))
            if a + ln > lim:
                continue
            g[a:a + ln] -= rng.uniform(30, 50) * np.sin(np.linspace(0, np.pi, ln))[: len(g[a:a + ln])]
    return np.clip(g, 39, 401)


# ------------------------------------------------------------------ writing

def write_patient(out_dir: Path, meta: Dict[str, Any], ev_true: List[Event], ev_logged: List[Event],
                  g_true: np.ndarray, daily_rows: List[Dict[str, Any]], rng: np.random.Generator, protect_from: int | None = None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    times = pd.date_range(START + timedelta(minutes=DT), periods=len(g_true), freq=f"{DT}min")
    g_obs = add_cgm_noise(g_true, rng, protect_from)
    write_dexcom_csv(out_dir / "cgm.csv", times, g_obs)
    pd.DataFrame({"time": times, "glucose": g_true}).to_csv(out_dir / "truth_glucose.csv", index=False, lineterminator="\n")
    pd.DataFrame(daily_rows).to_csv(out_dir / "daily.csv", index=False, lineterminator="\n")
    (out_dir / "events.json").write_text(json.dumps([e.to_dict() for e in ev_logged], indent=0), encoding="utf-8")
    (out_dir / "events_true.json").write_text(json.dumps([e.to_dict() for e in ev_true], indent=0), encoding="utf-8")
    # validation path: read the CSV back exactly as a real export would be read
    series = ingest_csv(out_dir / "cgm.csv")
    meta = dict(meta)
    meta["data_quality"] = series.quality_report()
    (out_dir / "patient.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta["data_quality"]


def generate(n_patients: int = N_PATIENTS, demo_only: bool = False, seed: int = COHORT_SEED, verbose: bool = True) -> None:
    rng = np.random.default_rng(seed)
    n = 1 if demo_only else n_patients
    if verbose:
        print(f"Sampling {n} patient(s)...")
    metas = [sample_patient(np.random.default_rng(seed + i), i) for i in range(n)]
    ev = [generate_events(m, np.random.default_rng(seed + 1000 + i)) for i, m in enumerate(metas)]
    ev_true = [a for a, _ in ev]
    ev_logged = [b for _, b in ev]
    if verbose:
        print(f"Simulating {N_DAYS} days x {n} patients (batched)...")
    G, daily, _ = simulate_cohort(metas, ev_true, verbose)
    for i, m in enumerate(metas):
        out = DEMO_PATIENT_DIR if i == DEMO_INDEX else COHORT_DIR / m["patient_id"]
        protect = None
        if i == DEMO_INDEX:   # the demo moment must sit on a clean sensor day: no dropouts in the 24 h before the anchor
            from backend.config import DEMO_ANCHOR
            protect = int((datetime.fromisoformat(DEMO_ANCHOR) - timedelta(hours=24) - START).total_seconds() // 60 // DT)
        q = write_patient(out, m, ev_true[i], ev_logged[i], G[i], daily[i], np.random.default_rng(seed + 2000 + i), protect)
        if verbose:
            print(f"  {m['patient_id']}: mean glucose {np.mean(G[i]):.0f}  TIR {np.mean((G[i] >= 70) & (G[i] <= 180)):.2f}  quality {q['data_quality']:.2f} -> {out.relative_to(DATA_DIR.parent.parent)}")
    if verbose:
        print("done")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-only", action="store_true")
    ap.add_argument("--n", type=int, default=N_PATIENTS)
    ap.add_argument("--seed", type=int, default=COHORT_SEED)
    args = ap.parse_args()
    generate(args.n, args.demo_only, args.seed)


if __name__ == "__main__":
    main()
