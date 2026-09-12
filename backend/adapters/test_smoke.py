import numpy as np
import pandas as pd

from backend.adapters.csv_ingest import ingest_csv, write_dexcom_csv, write_libre_csv, validate_series


def _series(n=300, start="2025-06-01T00:00"):
    t = pd.date_range(start, periods=n, freq="5min")
    g = 120 + 30 * np.sin(np.arange(n) / 20.0)
    return t, g


def test_dexcom_roundtrip(tmp_path):
    t, g = _series()
    g[50:55] = np.nan            # dropout
    g[100] = g[99] + 40          # artifact (8 mg/dL/min)
    p = tmp_path / "dex.csv"
    write_dexcom_csv(p, t, g)
    s = ingest_csv(p)
    assert s.source_format == "dexcom"
    assert len(s.times) >= 299
    assert any(gp["minutes"] >= 15 for gp in s.gaps)
    assert s.artifact.any()
    assert 0.0 <= s.data_quality <= 1.0
    assert s.staleness_min == 0.0


def test_libre_roundtrip(tmp_path):
    t, g = _series(n=100)
    p = tmp_path / "libre.csv"
    write_libre_csv(p, t, g)
    s = ingest_csv(p)
    assert s.source_format == "libre"
    assert np.nanmax(np.abs(s.glucose[s.valid] - np.round(g[s.valid]))) < 1.0


def test_staleness_lowers_quality():
    t, g = _series(n=288)
    raw = pd.DataFrame({"time": t, "glucose": g})
    fresh = validate_series(raw, now=t[-1].to_pydatetime())
    stale = validate_series(raw, now=(t[-1] + pd.Timedelta("45min")).to_pydatetime())
    assert stale.staleness_min == 45.0
    assert stale.data_quality < fresh.data_quality
