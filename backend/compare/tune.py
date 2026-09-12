"""Tuning helper for /compare: run the bank with a given override set and dosing ratios, print the
divergence table. Usage: python -m backend.compare.tune [config-name]"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("GLUCOPILOT_LIVE_CLOCK", "0")

from backend.compare import engine as E   # noqa: E402
from backend.engine import fast           # noqa: E402

CONFIGS = {
    # stated persona ratios, fitted physiology untouched
    "stated": {"overrides": {}, "ratios": {"demo": 37.0, "priya": 10.0, "marcus": 8.0}},
    # ratios titrated on the fitted physiology
    "calibrated": {"overrides": {}, "ratios": None},
    # tuned physiology (within the plausible ranges) + calibrated ratios
    "tuned": {"overrides": {"priya": {"si_tod0": 0.55, "si_tod1": 0.56, "si_tod2": 0.64, "tau_carb": 26.0},
                             "marcus": {"carb_ratio": 0.72, "si_tod0": 0.80, "si_tod1": 0.90, "si_tod2": 1.15, "sleep_debt_coef": 0.38, "tau_carb": 30.0}},
              "ratios": None},
}


def run(name: str, n: int = 100) -> bool:
    cfg = CONFIGS[name]
    E._TWINS.clear(); E._POP = None
    twins = E.get_twins()
    for pid, tw in twins.items():
        if cfg["overrides"].get(E.NAME_OF[pid]):
            E.apply_overrides(tw, cfg["overrides"][E.NAME_OF[pid]])
        cal = float(fast.calibrate_carb_ratio(tw.params))
        tw.profile["carb_ratio_g_per_u"] = cfg["ratios"][pid] if cfg["ratios"] else round(cal)
        print(f"  {E.NAME_OF[pid]:<7} dosing 1 u : {tw.profile['carb_ratio_g_per_u']:g} g (physiology says {cal:.0f})  glucose now {tw.state_now()[0].glucose:.0f}")
    ok_all = True
    for item in E.BANK:
        t1 = time.time()
        res = E.run_all(item, n=n)
        d = res["divergence"]
        heads = [res["personal"][w]["headline"] for w in ("alex", "priya", "marcus")]
        ok_all &= d["ok"]
        print(f"  {item['slug']:<11} {heads} peaks={d['peaks']} lows={[res['personal'][w]['low'] for w in ('alex','priya','marcus')]} spread={d['peak_spread']} dt={d['peak_time_spread_min']} {'ok' if d['ok'] else 'NOT OK'} pop={res['population']['headline']}/{res['population']['peak']} ({time.time() - t1:.0f}s)")
    print(f"== {name}: all six diverge = {ok_all}")
    return ok_all


if __name__ == "__main__":
    names = sys.argv[1:] or ["stated", "calibrated", "tuned"]
    for nm in names:
        print(f"== config {nm}")
        run(nm)
