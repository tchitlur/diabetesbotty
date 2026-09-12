"""Validation 5: DCCT reproduction. A1c 9 vs 7 -> 10-year retinopathy risk.

Writes validation/plots/dcct_reproduction.png and returns the numbers.
Run: python -m backend.validation.dcct
"""
from __future__ import annotations

import json
from typing import Dict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backend.config import PLOTS_DIR, VALIDATION_DIR
from backend.schema.state import State
from backend.engine.slow import dcct_check, run_slow, week_for_a1c, ORGANS, ORGAN_LABEL


def main() -> Dict[str, float]:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    res = dcct_check()
    a1cs = np.linspace(6.0, 11.0, 11)
    curves = {k: [] for k in ORGANS}
    for a in a1cs:
        r = run_slow(week_for_a1c(float(a)), State())
        for k in ORGANS:
            curves[k].append(100 * r.probabilities[k])
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.8))
    ax[0].bar(["A1c 9 %", "A1c 7 %"], [100 * res["p_retinopathy_a1c9"], 100 * res["p_retinopathy_a1c7"]], color=["tab:red", "tab:green"])
    ax[0].set_ylabel("10-year retinopathy probability (%)")
    ax[0].set_title(f"A1c 9 -> 7: {res['reduction_pct']:.0f} % lower risk (DCCT: 76 %)\nhazard ratio {res['hazard_ratio']:.2f}")
    for i, v in enumerate([res["p_retinopathy_a1c9"], res["p_retinopathy_a1c7"]]):
        ax[0].text(i, 100 * v + 0.5, f"{100 * v:.1f} %", ha="center")
    for k in ORGANS:
        ax[1].plot(a1cs, curves[k], marker="o", ms=3, label=ORGAN_LABEL[k])
    ax[1].set_xlabel("steady A1c-equivalent (%)")
    ax[1].set_ylabel("10-year probability (%)")
    ax[1].set_title("Organ risk vs glycaemia (no alcohol, normal sleep/hydration)")
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "dcct_reproduction.png", dpi=110)
    (VALIDATION_DIR / "dcct.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"DCCT: A1c 9 -> {100 * res['p_retinopathy_a1c9']:.1f} %, A1c 7 -> {100 * res['p_retinopathy_a1c7']:.1f} %, reduction {res['reduction_pct']:.1f} % (target ~76 %)")
    return res


if __name__ == "__main__":
    main()
