"""Fast-layer physiology: Hovorka (2004) glucose-insulin model plus the
GlucoPilot extensions (gut, liver/muscle glycogen, alcohol, caffeine,
exercise, ketones, hydration, energy).

Everything here is written for numpy broadcasting so a batch of B trajectories
(Monte Carlo samples, cohort patients, fitting windows) integrates in one pass.

State vector x has shape (B, NS). Inputs u have shape (B, NU). Params p is a
dict of floats or (B,) arrays.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

MG_PER_MMOL = 18.016
MMOL_PER_G = 5.551

# ------------------------------------------------------------------ indices
IDX: Dict[str, int] = {
    "Q1": 0, "Q2": 1, "S1": 2, "S2": 3, "I": 4, "x1": 5, "x2": 6, "x3": 7,
    "D1": 8, "D2": 9, "L": 10, "M": 11, "BAC": 12, "Agut": 13, "C": 14, "Cgut": 15,
    "K": 16, "H": 17, "ex": 18, "anaer": 19, "hang": 20,
}
NS = len(IDX)
HIDDEN_KEYS = ["Q2", "S1", "S2", "x1", "x2", "x3", "Agut", "Cgut", "ex", "anaer", "hang"]

UIDX: Dict[str, int] = {
    "carb": 0,      # g/min
    "tau_g": 1,     # min (effective carb absorption time constant)
    "bolus": 2,     # mU/min
    "basal": 3,     # mU/min (0 => use params basal)
    "alc": 4,       # g/min
    "caf": 5,       # mg/min
    "ex_int": 6,    # aerobic intensity 0..1
    "an_int": 7,    # anaerobic intensity 0..1
    "water": 8,     # ml/min
    "tod": 9,       # 0,1,2 time-of-day bin
    "ill": 10,      # illness severity 0..1
    "stress": 11,   # stress severity 0..1
    "ex_long": 12,  # 1 if exercise has lasted > 60 min
    "basal_override": 13,  # 1 if a basal event is active
}
NU = len(UIDX)


def _g(p: Dict, k: str):
    return p[k]


def si_multiplier(x: np.ndarray, u: np.ndarray, p: Dict) -> np.ndarray:
    """Composite insulin-sensitivity multiplier (dimensionless)."""
    tod = u[:, UIDX["tod"]]
    si_tod = np.where(tod < 0.5, p["si_tod0"], np.where(tod < 1.5, p["si_tod1"], p["si_tod2"]))
    M = x[:, IDX["M"]]
    C = x[:, IDX["C"]]
    ex = x[:, IDX["ex"]]
    depletion = 1.0 + p["muscle_depletion_si_gain"] * np.clip(1.0 - M / p["muscle_M_max"], 0, 1)
    exercise = 1.0 + p["exercise_si_gain"] * ex * p["exercise_mult"]
    caffeine = 1.0 / (1.0 + p["caffeine_si_drop_per_200mg"] * C / 200.0)
    illness = 1.0 - p["illness_si_drop"] * u[:, UIDX["ill"]]
    stress = 1.0 - p["stress_si_drop"] * u[:, UIDX["stress"]]
    medium = p["insulin_sensitivity"]
    return si_tod * medium * depletion * exercise * caffeine * illness * stress


def rhs(x: np.ndarray, u: np.ndarray, p: Dict) -> np.ndarray:
    """Right-hand side of the fast-layer ODE. x:(B,NS) u:(B,NU) -> dx:(B,NS)."""
    Q1, Q2 = x[:, 0], x[:, 1]
    S1, S2, I = x[:, 2], x[:, 3], x[:, 4]
    x1, x2, x3 = x[:, 5], x[:, 6], x[:, 7]
    D1, D2 = x[:, 8], x[:, 9]
    L, M = x[:, 10], x[:, 11]
    BAC, Agut = x[:, 12], x[:, 13]
    C, Cgut = x[:, 14], x[:, 15]
    K, H = x[:, 16], x[:, 17]
    ex, anaer, hang = x[:, 18], x[:, 19], x[:, 20]

    BW = p["BW"]
    VG, VI = p["VG"], p["VI"]
    G_mmol = Q1 / VG
    G_mgdl = G_mmol * MG_PER_MMOL

    si = si_multiplier(x, u, p)

    # ---------------- insulin subsystem (Hovorka 2004)
    basal_default = p["basal_u_per_h"] * p["basal_drift"] * 1000.0 / 60.0  # mU/min
    basal = np.where(u[:, UIDX["basal_override"]] > 0.5, u[:, UIDX["basal"]] * p["basal_drift"], basal_default)
    u_ins = (u[:, UIDX["bolus"]] + basal) / BW  # mU/kg/min
    tmaxI = p["tmaxI"]
    dS1 = u_ins - S1 / tmaxI
    dS2 = S1 / tmaxI - S2 / tmaxI
    UI = S2 / tmaxI
    dI = UI / VI - p["ke"] * I
    dx1 = -p["ka1"] * x1 + p["ka1"] * p["SIT"] * si * I
    dx2 = -p["ka2"] * x2 + p["ka2"] * p["SID"] * si * I
    dx3 = -p["ka3"] * x3 + p["ka3"] * p["SIE"] * si * I

    # ---------------- gut absorption (two compartments; fat/fiber scale tau via input)
    tau_g = np.maximum(u[:, UIDX["tau_g"]], 5.0)
    carb_in = u[:, UIDX["carb"]] * p["carb_ratio"]  # bioavailable g/min
    dD1 = carb_in - D1 / tau_g
    dD2 = D1 / tau_g - D2 / tau_g
    UG_g = D2 / tau_g                     # g/min
    UG = UG_g * MMOL_PER_G / BW           # mmol/kg/min

    # ---------------- hepatic glucose output
    Lh, Lfloor = p["liver_L_half"], p["liver_L_floor"]
    gly_fac = (Lfloor + (1 - Lfloor) * L / (L + Lh)) / (Lfloor + (1 - Lfloor) * 60.0 / (60.0 + Lh))
    alc_drive = 0.6 * BAC + p["alcohol_hangover_gain"] * hang
    alc_sup = np.clip(1.0 - p["alcohol_gain"] * p["alcohol_egp_suppression_per_bac"] * alc_drive,
                      p["alcohol_egp_floor"], 1.0)
    stress_ill = 1.0 + p["illness_egp_gain"] * u[:, UIDX["ill"]] + p["stress_egp_gain"] * u[:, UIDX["stress"]]
    anaer_fac = 1.0 + p["exercise_anaerobic_egp_gain"] * anaer * p["exercise_mult"]
    EGP = np.maximum(p["EGP0"] * (1.0 - x3) * gly_fac * alc_sup * stress_ill * anaer_fac, 0.0)

    # ---------------- glucose subsystem
    ex_int = u[:, UIDX["ex_int"]]
    F01 = p["F01"] * (1.0 + p["exercise_uptake_gain"] * ex_int * p["exercise_mult"])
    F01c = np.where(G_mmol >= p["G_F01_threshold_mmol"], F01, F01 * G_mmol / p["G_F01_threshold_mmol"])
    FR = np.where(G_mmol >= p["renal_threshold_mmol"], p["renal_k"] * (G_mmol - p["renal_threshold_mmol"]) * VG, 0.0)
    dQ1 = -F01c - x1 * Q1 + p["k12"] * Q2 - FR + UG + EGP
    dQ2 = x1 * Q1 - (p["k12"] + x2) * Q2

    # ---------------- glycogen stores (bookkeeping in grams)
    EGP_g = EGP * BW / MMOL_PER_G
    disposal_g = x2 * Q2 * BW / MMOL_PER_G
    an_int = u[:, UIDX["an_int"]]
    ex_drive = (ex_int + 0.7 * an_int) * p["exercise_mult"]
    glycogenolysis = 0.3 * EGP_g * L / (L + Lh)
    dL = (p["liver_store_frac"] * UG_g * np.clip(1.0 - L / p["liver_L_max"], 0, 1)
          - glycogenolysis - p["liver_exercise_drain_g_per_min"] * ex_drive * (L > 0.5))
    dM = (p["muscle_refill_frac"] * disposal_g * np.clip(1.0 - M / p["muscle_M_max"], 0, 1)
          - p["muscle_drain_g_per_min"] * ex_drive * (M > 0.5))

    # ---------------- alcohol (Widmark)
    abs_a = p["alcohol_absorption_tau_min"]
    dAgut = u[:, UIDX["alc"]] - Agut / abs_a
    elim = p["alcohol_elimination_g_per_dl_per_h"] / 60.0
    dBAC = (Agut / abs_a) / (p["alcohol_widmark_r"] * BW * 10.0) - elim * BAC / (BAC + 0.003)
    tau_h = p["alcohol_hangover_tau_min"]
    dhang = np.where(BAC > hang, (BAC - hang) / 150.0, -hang / tau_h)

    # ---------------- caffeine
    abs_c = p["caffeine_absorption_tau_min"]
    kc = np.log(2.0) / p["caffeine_half_life_min"]
    dCgut = u[:, UIDX["caf"]] - Cgut / abs_c
    dC = Cgut / abs_c - kc * C

    # ---------------- exercise memory
    dex = np.where(ex_int > ex, (ex_int - ex) / 20.0, -ex / p["exercise_effect_tau_min"])
    danaer = np.where(an_int > anaer, (an_int - anaer) / 10.0, -anaer / p["exercise_anaerobic_tau_min"])

    # ---------------- ketones
    low_ins = 1.0 / (1.0 + (I / p["ketones_insulin_half_mU"]) ** 4)
    drive = low_ins * (0.3 + 0.7 * np.clip(1.0 - L / p["liver_L_max"], 0, 1)) \
        + p["ketones_exercise_prod_gain"] * u[:, UIDX["ex_long"]] * ex_int
    kK = np.log(2.0) / p["ketones_clear_half_life_min"]
    dK = p["ketones_prod_rate"] * drive - kK * (K - p["ketones_baseline"])

    # ---------------- hydration
    over = np.maximum(G_mgdl - p["hydration_hyper_threshold_mgdl"], 0.0) / 100.0
    dH = (-p["hydration_osmotic_loss_per_min_at_100_over"] * over
          - p["alcohol_hydration_loss_per_bac_min"] * BAC / 0.05
          + u[:, UIDX["water"]] / p["hydration_ml_to_full"]
          + (p["hydration_recovery_setpoint"] - H) / p["hydration_recovery_tau_min"])

    dx = np.stack([dQ1, dQ2, dS1, dS2, dI, dx1, dx2, dx3, dD1, dD2, dL, dM,
                   dBAC, dAgut, dC, dCgut, dK, dH, dex, danaer, dhang], axis=1)
    return dx


def clamp(x: np.ndarray, p: Dict) -> np.ndarray:
    x = np.maximum(x, 0.0)
    x[:, IDX["L"]] = np.minimum(x[:, IDX["L"]], p["liver_L_max"])
    x[:, IDX["M"]] = np.minimum(x[:, IDX["M"]], p["muscle_M_max"])
    x[:, IDX["H"]] = np.clip(x[:, IDX["H"]], 0.0, 1.0)
    x[:, IDX["K"]] = np.maximum(x[:, IDX["K"]], 0.5 * p["ketones_baseline"])
    x[:, IDX["ex"]] = np.clip(x[:, IDX["ex"]], 0.0, 1.0)
    x[:, IDX["anaer"]] = np.clip(x[:, IDX["anaer"]], 0.0, 1.0)
    return x


def glucose_mgdl(x: np.ndarray, p: Dict) -> np.ndarray:
    return x[..., IDX["Q1"]] / p["VG"] * MG_PER_MMOL


def energy_score(x: np.ndarray, p: Dict) -> np.ndarray:
    G = glucose_mgdl(x, p)
    C = x[..., IDX["C"]]
    H = x[..., IDX["H"]]
    BAC = x[..., IDX["BAC"]]
    K = x[..., IDX["K"]]
    e = (p["energy_base"]
         - p["energy_glucose_coef"] * np.abs(G - 100.0)
         - p["energy_sleep_debt_coef"] * p["sleep_debt"]
         - p["energy_dehydration_coef"] * np.maximum(p["hydration_recovery_setpoint"] - 0.05 - H, 0.0)
         + p["energy_caffeine_boost"] * np.minimum(C, 200.0) / 200.0
         - p["energy_alcohol_penalty"] * np.minimum(BAC, 0.10) / 0.10
         - p["energy_ketone_penalty"] * (K > 0.6))
    return np.clip(e, 0.0, 100.0)


def steady_state_init(G_mgdl: np.ndarray, I_mU: np.ndarray, p: Dict, si: np.ndarray | float = 1.0) -> np.ndarray:
    """Initialise the Hovorka sub-states consistent with observed glucose and
    (estimated) plasma insulin. Returns (B, NS) with extension states zeroed."""
    G_mgdl = np.atleast_1d(np.asarray(G_mgdl, dtype=float))
    I_mU = np.atleast_1d(np.asarray(I_mU, dtype=float))
    B = max(G_mgdl.shape[0], I_mU.shape[0])
    x = np.zeros((B, NS))
    Q1 = G_mgdl / MG_PER_MMOL * p["VG"]
    x1 = p["SIT"] * si * I_mU
    x2 = p["SID"] * si * I_mU
    x3 = p["SIE"] * si * I_mU
    Q2 = x1 * Q1 / (p["k12"] + x2)
    u_ins = I_mU * p["ke"] * p["VI"]   # mU/kg/min needed to hold I
    S = u_ins * p["tmaxI"]
    x[:, IDX["Q1"]] = Q1
    x[:, IDX["Q2"]] = Q2
    x[:, IDX["S1"]] = S
    x[:, IDX["S2"]] = S
    x[:, IDX["I"]] = I_mU
    x[:, IDX["x1"]] = x1
    x[:, IDX["x2"]] = x2
    x[:, IDX["x3"]] = np.minimum(x3, 0.95)
    return x


def basal_plasma_insulin(p: Dict) -> np.ndarray | float:
    """Plasma insulin (mU/L) sustained by the configured basal rate."""
    rate = p["basal_u_per_h"] * p["basal_drift"] * 1000.0 / 60.0 / p["BW"]  # mU/kg/min
    return rate / (p["ke"] * p["VI"])


def integrate(x0: np.ndarray, inputs: np.ndarray, p: Dict, dt_min: float = 5.0, substeps: int = 2) -> np.ndarray:
    """Fixed-step RK4 with piecewise-constant inputs.

    x0: (B, NS); inputs: (T, B, NU) or (T, NU); returns X: (T+1, B, NS).
    """
    x = np.array(x0, dtype=float, copy=True)
    if x.ndim == 1:
        x = x[None, :]
    B = x.shape[0]
    T = inputs.shape[0]
    if inputs.ndim == 2:
        inputs = np.broadcast_to(inputs[:, None, :], (T, B, NU))
    X = np.empty((T + 1, B, NS))
    X[0] = x
    h = dt_min / substeps
    for k in range(T):
        u = inputs[k]
        for _ in range(substeps):
            k1 = rhs(x, u, p)
            k2 = rhs(x + 0.5 * h * k1, u, p)
            k3 = rhs(x + 0.5 * h * k2, u, p)
            k4 = rhs(x + h * k3, u, p)
            x = x + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
            x = clamp(x, p)
        X[k + 1] = x
    return X


def integrate_solve_ivp(x0: np.ndarray, inputs: np.ndarray, p: Dict, dt_min: float = 5.0) -> np.ndarray:
    """Reference integrator using scipy.solve_ivp (RK45) step by step. B must be 1.
    Used by tests to verify the fast RK4 path; too slow for Monte Carlo."""
    from scipy.integrate import solve_ivp

    x = np.array(x0, dtype=float, copy=True).reshape(1, NS)
    T = inputs.shape[0]
    if inputs.ndim == 3:
        inputs = inputs[:, 0, :]
    X = np.empty((T + 1, 1, NS))
    X[0] = x
    for k in range(T):
        u = inputs[k][None, :]
        sol = solve_ivp(lambda t, y: rhs(y[None, :], u, p)[0], (0.0, dt_min), x[0], method="RK45", rtol=1e-6, atol=1e-8)
        x = clamp(sol.y[:, -1][None, :].copy(), p)
        X[k + 1] = x
    return X


def steady_basal_insulin(p: Dict, G_target_mgdl: float = 115.0, si: float | None = None) -> float:
    """Plasma insulin (mU/L) at which the Hovorka model holds G_target with no
    meals (bisection on the glucose balance). si defaults to the daytime bin."""
    if si is None:
        si = float(p["si_tod1"]) * float(p.get("insulin_sensitivity", 1.0))
    Q1 = G_target_mgdl / MG_PER_MMOL * p["VG"]
    Lh, Lfloor = p["liver_L_half"], p["liver_L_floor"]
    L = 60.0
    gly = (Lfloor + (1 - Lfloor) * L / (L + Lh)) / (Lfloor + (1 - Lfloor) * 60.0 / (60.0 + Lh))

    def bal(I: float) -> float:
        x1, x2, x3 = p["SIT"] * si * I, p["SID"] * si * I, min(p["SIE"] * si * I, 0.95)
        Q2 = x1 * Q1 / (p["k12"] + x2)
        EGP = max(p["EGP0"] * (1 - x3) * gly, 0.0)
        return EGP - p["F01"] - x2 * Q2

    lo, hi = 0.01, 40.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bal(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def basal_rate_for_insulin(I_mU: float, p: Dict) -> float:
    """U/h of basal delivery that sustains plasma insulin I_mU."""
    return I_mU * p["ke"] * p["VI"] * p["BW"] * 60.0 / 1000.0


def steady_basal_rate(p: Dict, G_target_mgdl: float = 115.0) -> float:
    return basal_rate_for_insulin(steady_basal_insulin(p, G_target_mgdl), p)


def calibrate_carb_ratio(p: Dict, carbs_g: float = 60.0, G0: float = 120.0, residual_mgdl: float = 35.0) -> float:
    """Clinical carb ratio (g per unit) for this physiology, the way a clinician
    titrates: the bolus for a 60 g meal that minimises time spent above
    G0 + residual over 5 h while never dropping below 80 mg/dL. One batched
    integration over a log-spaced grid of 40 candidate doses (deterministic)."""
    from backend.engine.simulate import events_to_inputs, initial_vector  # local import to avoid a cycle
    from backend.schema.state import State
    from backend.schema.events import Event
    from datetime import datetime

    I0 = steady_basal_insulin(p, G0)
    st = State(glucose=G0, plasma_insulin=float(I0), liver_glycogen=60.0)
    t0 = datetime(2025, 1, 6, 12, 0)
    doses = np.geomspace(0.2, 25.0, 40)
    T = 300 // 5
    base_u = events_to_inputs([Event(type="meal", start_time=t0.isoformat(), carbs_g=carbs_g)], t0, T, 5, p)
    inputs = np.repeat(base_u[:, None, :], len(doses), axis=1)
    inputs[0, :, UIDX["bolus"]] += doses * 1000.0 / 5.0          # units -> mU/min over the first 5-min step
    x0 = np.repeat(initial_vector(st, p), len(doses), axis=0)
    X = integrate(x0, inputs, p, 5.0, substeps=2)
    G = glucose_mgdl(X, p)                                        # (T+1, n_doses)
    above = np.maximum(G - (G0 + residual_mgdl), 0.0).mean(axis=0)
    below = np.maximum(80.0 - G, 0.0).mean(axis=0)
    end_off = np.abs(G[-1] - G0 - residual_mgdl)
    cost = above + 4.0 * below + 0.2 * end_off
    best = float(doses[int(np.argmin(cost))])
    return float(carbs_g / best)
