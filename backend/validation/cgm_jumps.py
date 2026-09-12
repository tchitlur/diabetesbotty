"""Adjacent-point jump statistics for a CGM file: how spiky the synthetic sensor trace is.

Usage: python -m backend.validation.cgm_jumps [path/to/cgm.csv]
Prints |G(t+5) - G(t)| statistics over consecutive raw readings 5 minutes apart."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backend.config import DEMO_PATIENT_DIR


def jump_stats(path: Path) -> dict:
    df = pd.read_csv(path)
    tcol = next(c for c in df.columns if "time" in c.lower())
    gcol = next(c for c in df.columns if "glucose" in c.lower())
    t = pd.to_datetime(df[tcol])
    g = pd.to_numeric(df[gcol], errors="coerce").to_numpy(dtype=float)
    dt = t.diff().dt.total_seconds().to_numpy() / 60.0
    d = np.abs(np.diff(g))
    ok = (dt[1:] == 5.0) & ~np.isnan(d)
    d = d[ok]
    return {"n_pairs": int(len(d)), "mean_abs_jump": float(np.mean(d)), "median_abs_jump": float(np.median(d)),
            "p95_abs_jump": float(np.percentile(d, 95)), "max_abs_jump": float(np.max(d)),
            "share_over_10": float(np.mean(d > 10)), "share_over_20": float(np.mean(d > 20)),
            "lag1_autocorr": float(np.corrcoef(g[:-1][~np.isnan(g[:-1]) & ~np.isnan(g[1:])], g[1:][~np.isnan(g[:-1]) & ~np.isnan(g[1:])])[0, 1])}


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEMO_PATIENT_DIR / "cgm.csv"
    s = jump_stats(path)
    print(f"{path}")
    for k, v in s.items():
        print(f"  {k:18s} {v:.3f}" if isinstance(v, float) else f"  {k:18s} {v}")


if __name__ == "__main__":
    main()
