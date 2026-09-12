"""Run every validation script and assemble RESULTS.md.

python -m backend.validation.run_all          # ~8-10 minutes (30 fits + Monte Carlo calibration)
python -m backend.validation.run_all --quick  # ~2 minutes (fewer patients / anchors)
"""
from __future__ import annotations

import argparse
import time

from backend.validation import sanity, param_recovery, forecast_rmse, hypo_calibration, alcohol_night, dcct, results


def main(quick: bool = False) -> None:
    tic = time.time()
    print("[1/6] sanity plots"); sanity.main()
    print("[2/6] parameter recovery"); param_recovery.main(max_patients=8 if quick else 30)
    print("[3/6] forecast RMSE"); forecast_rmse.main(n_patients=3 if quick else 6)
    print("[4/6] hypo calibration"); hypo_calibration.main(n_patients=2 if quick else 4, per_day=4 if quick else 6)
    print("[5/6] alcohol night"); alcohol_night.main()
    print("[6/6] DCCT"); dcct.main()
    results.main()
    print(f"done in {time.time() - tic:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    main(ap.parse_args().quick)
