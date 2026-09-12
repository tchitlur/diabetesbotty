"""Validation 4: one demo-patient alcohol night. Twin (as logged) vs the
synthetic "actual" CGM, plus the twin's alcohol-free counterfactual, showing
the delayed low.

Writes validation/plots/alcohol_night.png and validation/alcohol_night.json.
Run: python -m backend.validation.alcohol_night [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
from typing import Dict, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backend.config import PLOTS_DIR, VALIDATION_DIR
from backend.api.twin import Twin
from backend.decision.replay import replay_day, suggest_day


def main(date: Optional[str] = None) -> Dict[str, object]:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    tw = Twin()
    if date is None:
        s = suggest_day(tw)
        date = s["suggested"]["date"] if s["suggested"] else "2025-08-09"
    r1 = replay_day(tw, date)
    r0 = replay_day(tw, date, alcohol_scale=0.0)
    t = np.arange(len(r1.times)) * 5 / 60.0 + 6.0     # hours since midnight
    actual = np.array([np.nan if x is None else x for x in r1.actual])
    drinks = [e for e in r1.events if e.type == "alcohol"]
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(t, actual, color="#333", lw=1.4, label="synthetic CGM (actual)")
    ax.plot(t, r1.simulated_original, color="tab:blue", lw=2, label="twin: events as logged")
    ax.plot(t, r0.simulated, color="tab:green", lw=2, ls="--", label="twin: same day, alcohol removed")
    ax.axhline(70, color="tab:red", ls=":", lw=1)
    for d in drinks:
        h = int(d.start_time[11:13]) + int(d.start_time[14:16]) / 60.0
        ax.axvspan(h, h + max(d.duration_min, 60) / 60.0, color="tab:purple", alpha=0.12)
        ax.text(h, 290, f"{d.label} ({d.alcohol_g:.0f} g alcohol, {d.carbs_g:.0f} g carbs)", fontsize=9, color="tab:purple")
    night = [i for i, x in enumerate(r1.times) if x >= date + "T22:00"]
    i_min = night[int(np.argmin(np.array(r1.simulated_original)[night]))]
    ax.annotate(f"twin nadir {r1.simulated_original[i_min]:.0f} mg/dL at {r1.times[i_min][11:16]}", (t[i_min], r1.simulated_original[i_min]),
                xytext=(t[i_min] - 6, r1.simulated_original[i_min] - 30), arrowprops=dict(arrowstyle="->"), fontsize=9)
    j = [i for i in night if not np.isnan(actual[i])]
    if j:
        i_a = j[int(np.argmin(actual[j]))]
        ax.annotate(f"actual nadir {actual[i_a]:.0f} at {r1.times[i_a][11:16]}", (t[i_a], actual[i_a]), xytext=(t[i_a] - 9, actual[i_a] + 60), arrowprops=dict(arrowstyle="->"), fontsize=9)
    ax.set_xlim(6, 32)
    ax.set_xticks(range(6, 33, 2), [f"{h % 24:02d}:00" for h in range(6, 33, 2)])
    ax.set_ylim(30, 320)
    ax.set_xlabel(f"{date} 06:00 -> next day 08:00")
    ax.set_ylabel("glucose (mg/dL)")
    ax.set_title(f"Demo patient, {date}: delayed low after drinking. Twin re-anchored at 06:00 and 18:00 on its filtered state.")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "alcohol_night.png", dpi=110)
    tw_night = np.array(r1.simulated_original)[night]
    no_night = np.array(r0.simulated)[night]
    act_night = actual[night]
    out = {"date": date, "drinks": [d.model_dump() for d in drinks],
           "overnight_min_actual": float(np.nanmin(act_night)) if not np.all(np.isnan(act_night)) else None,
           "overnight_min_twin": float(tw_night.min()), "overnight_min_twin_no_alcohol": float(no_night.min()),
           "twin_nadir_time": r1.times[i_min], "hypo_minutes_twin": r1.hypo_minutes_original, "hypo_minutes_no_alcohol": r0.hypo_minutes_modified,
           "overlay_rmse_mgdl": float(np.sqrt(np.nanmean((np.array(r1.simulated_original) - actual) ** 2)))}
    (VALIDATION_DIR / "alcohol_night.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{date}: twin overnight min {out['overnight_min_twin']:.0f} (actual {out['overnight_min_actual']}), without alcohol {out['overnight_min_twin_no_alcohol']:.0f}; overlay RMSE {out['overlay_rmse_mgdl']:.1f}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    main(ap.parse_args().date)
