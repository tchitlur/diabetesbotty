"""Checkpoint-2 sanity plots: alcohol delayed low and exercise drop.

Run:  python -m backend.validation.sanity
Writes validation/plots/sanity_alcohol.png and sanity_exercise.png
"""
from __future__ import annotations

import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backend.config import PLOTS_DIR
from backend.schema.state import State
from backend.schema.events import Event
from backend.engine import fast
from backend.engine.params import build_params
from backend.engine.simulate import simulate
from backend.engine.montecarlo import run_monte_carlo


def main() -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    p = build_params()
    I0 = fast.steady_basal_insulin(p)
    st = State(glucose=130, plasma_insulin=I0, liver_glycogen=60)

    # ---- alcohol night: 4 beers 21:00-23:00 vs same carbs without alcohol
    t0 = "2025-03-07T21:00"
    beers = [Event(type="alcohol", start_time=t0, duration_min=120, alcohol_g=56, carbs_g=48, label="4 beers")]
    carbs_only = [Event(type="meal", start_time=t0, duration_min=120, carbs_g=48, label="same carbs, no alcohol")]
    tr_a = simulate(st, beers, p, 12 * 60, t0=t0)
    tr_c = simulate(st, carbs_only, p, 12 * 60, t0=t0)
    tr_0 = simulate(st, [], p, 12 * 60, t0=t0)
    h = tr_a.t_min / 60.0
    fig, ax = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    ax[0].plot(h, tr_a.series["glucose"], label="4 beers (56 g alcohol + 48 g carbs)", color="tab:red", lw=2)
    ax[0].plot(h, tr_c.series["glucose"], label="48 g carbs, no alcohol", color="tab:blue", lw=1.5)
    ax[0].plot(h, tr_0.series["glucose"], label="nothing", color="gray", ls="--")
    ax[0].axhline(70, color="k", ls=":", lw=1)
    ax[0].set_ylabel("glucose (mg/dL)")
    i = int(np.argmin(tr_a.series["glucose"]))
    ax[0].annotate(f"nadir {tr_a.min_glucose:.0f} mg/dL at +{h[i]:.1f} h", (h[i], tr_a.min_glucose),
                   xytext=(h[i] - 4, tr_a.min_glucose + 40), arrowprops=dict(arrowstyle="->"))
    ax[0].legend(loc="upper right")
    ax[0].set_title("Alcohol: delayed low from suppressed hepatic glucose output")
    ax[1].plot(h, tr_a.series["blood_alcohol"], color="tab:red", label="BAC (g/dL)")
    ax[1].plot(h, tr_a.series["_hangover"], color="tab:orange", label="lingering suppression state")
    ax[1].plot(h, tr_a.series["liver_glycogen"] / 100.0, color="tab:green", label="liver glycogen / 100 g")
    ax[1].set_xlabel("hours after first drink (21:00)")
    ax[1].legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "sanity_alcohol.png", dpi=110)

    # ---- exercise: aerobic run vs anaerobic lift vs nothing
    t0 = "2025-03-07T08:00"
    st2 = State(glucose=140, plasma_insulin=I0, liver_glycogen=60)
    run = [Event(type="exercise", start_time="2025-03-07T09:00", duration_min=30, exercise_kind="aerobic", intensity=0.6)]
    lift = [Event(type="exercise", start_time="2025-03-07T09:00", duration_min=45, exercise_kind="anaerobic", intensity=0.7)]
    tr_r = simulate(st2, run, p, 6 * 60, t0=t0)
    tr_l = simulate(st2, lift, p, 6 * 60, t0=t0)
    tr_n = simulate(st2, [], p, 6 * 60, t0=t0)
    h = tr_r.t_min / 60.0
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(h, tr_r.series["glucose"], label="30 min aerobic run @ 0.6", color="tab:green", lw=2)
    ax.plot(h, tr_l.series["glucose"], label="45 min anaerobic lift @ 0.7", color="tab:purple", lw=2)
    ax.plot(h, tr_n.series["glucose"], label="nothing", color="gray", ls="--")
    ax.axvspan(1.0, 1.5, color="tab:green", alpha=0.1)
    ax.axvspan(1.0, 1.75, color="tab:purple", alpha=0.05)
    ax.axhline(70, color="k", ls=":", lw=1)
    ax.set_xlabel("hours (exercise starts at +1 h)")
    ax.set_ylabel("glucose (mg/dL)")
    ax.set_title("Exercise: aerobic drop with lingering sensitivity; anaerobic transient rise")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "sanity_exercise.png", dpi=110)

    # ---- Monte Carlo timing
    tic = time.time()
    mc = run_monte_carlo(st, beers, p, {}, horizon_min=480, n=200, t0="2025-03-07T21:00")
    dt = time.time() - tic
    print(f"Monte Carlo 200 x 8h: {dt:.2f} s  P(hypo)={mc.p_hypo:.2f} P(hyper)={mc.p_hyper:.2f} TIR={mc.tir:.2f}")
    fig, ax = plt.subplots(figsize=(9, 4.5))
    hh = mc.t_min / 60.0
    ax.fill_between(hh, mc.p10, mc.p90, color="tab:red", alpha=0.2, label="p10-p90")
    ax.plot(hh, mc.median, color="tab:red", label="median")
    ax.axhline(70, color="k", ls=":", lw=1)
    ax.set_title(f"Monte Carlo (200 samples) after 4 beers: P(hypo 8h)={mc.p_hypo:.2f}")
    ax.set_xlabel("hours")
    ax.set_ylabel("glucose (mg/dL)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "sanity_montecarlo.png", dpi=110)
    print("wrote", PLOTS_DIR)


if __name__ == "__main__":
    main()
