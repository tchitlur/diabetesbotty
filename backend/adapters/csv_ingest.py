"""Layer 0: CGM CSV ingestion and validation.

Reads Dexcom Clarity and LibreView exports (format auto-detected from the
header), aligns readings to a 5-minute grid, detects gaps, flags rate-of-change
artifacts, tags sensor age, and computes staleness and a 0-1 data-quality
score. Synthetic data is written in Dexcom format and read back through this
same function so the quality score is real.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

ARTIFACT_ROC_MGDL_PER_MIN = 4.0
SENSOR_LIFE_DAYS = 10.0


@dataclass
class GlucoseSeries:
    times: pd.DatetimeIndex            # 5-min grid
    glucose: np.ndarray                # mg/dL, NaN where missing
    valid: np.ndarray                  # bool, False for missing or artifact
    artifact: np.ndarray               # bool
    sensor_age_days: np.ndarray        # float per point
    gaps: List[Dict[str, object]] = field(default_factory=list)
    staleness_min: float = 0.0
    data_quality: float = 0.0
    source_format: str = "unknown"
    n_raw: int = 0

    def last_valid_time(self) -> Optional[datetime]:
        idx = np.where(self.valid)[0]
        if len(idx) == 0:
            return None
        return self.times[idx[-1]].to_pydatetime()

    def last_valid_glucose(self) -> Optional[float]:
        idx = np.where(self.valid)[0]
        return float(self.glucose[idx[-1]]) if len(idx) else None

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({"time": self.times, "glucose": self.glucose, "valid": self.valid,
                             "artifact": self.artifact, "sensor_age_days": self.sensor_age_days})

    def quality_report(self) -> Dict[str, object]:
        return {
            "format": self.source_format,
            "n_raw": self.n_raw,
            "n_grid": int(len(self.times)),
            "coverage": float(np.mean(self.valid)) if len(self.valid) else 0.0,
            "n_gaps": len(self.gaps),
            "n_artifacts": int(np.sum(self.artifact)),
            "staleness_min": self.staleness_min,
            "data_quality": self.data_quality,
        }


# ------------------------------------------------------------------ parsing

def _detect_format(text: str) -> str:
    head = text[:4000].lower()
    if "glucose value (mg/dl)" in head or "event type" in head and "transmitter" in head:
        return "dexcom"
    if "historic glucose" in head or "libreview" in head or "scan glucose" in head:
        return "libre"
    if "timestamp" in head and "glucose" in head:
        return "generic"
    raise ValueError("Unrecognised CGM CSV format (expected Dexcom Clarity or LibreView export)")


def _parse_dexcom(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    cols = {c.lower(): c for c in df.columns}
    ts_col = next(c for k, c in cols.items() if k.startswith("timestamp"))
    g_col = next(c for k, c in cols.items() if k.startswith("glucose value"))
    if "event type" in cols:
        df = df[df[cols["event type"]].astype(str).str.upper().str.strip() == "EGV"]
    g = pd.to_numeric(df[g_col].replace({"High": 401, "Low": 39}), errors="coerce")
    t = pd.to_datetime(df[ts_col], errors="coerce")
    out = pd.DataFrame({"time": t, "glucose": g}).dropna(subset=["time"])
    return out


def _parse_libre(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    # LibreView exports carry 1-2 metadata lines before the header
    start = 0
    for i, ln in enumerate(lines[:5]):
        if "device timestamp" in ln.lower():
            start = i
            break
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    cols = {c.lower(): c for c in df.columns}
    ts_col = cols["device timestamp"]
    hist = next((c for k, c in cols.items() if k.startswith("historic glucose")), None)
    scan = next((c for k, c in cols.items() if k.startswith("scan glucose")), None)
    g = pd.to_numeric(df[hist], errors="coerce") if hist else pd.Series(np.nan, index=df.index)
    if scan:
        g = g.fillna(pd.to_numeric(df[scan], errors="coerce"))
    t = pd.to_datetime(df[ts_col], errors="coerce", format="%m-%d-%Y %I:%M %p")
    if t.isna().mean() > 0.5:  # other LibreView locales
        t = pd.to_datetime(df[ts_col], errors="coerce", format="mixed", dayfirst=False)
    return pd.DataFrame({"time": t, "glucose": g}).dropna(subset=["time"])


def _parse_generic(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    cols = {c.lower(): c for c in df.columns}
    ts_col = next(c for k, c in cols.items() if "time" in k)
    g_col = next(c for k, c in cols.items() if "glucose" in k)
    return pd.DataFrame({"time": pd.to_datetime(df[ts_col], errors="coerce"),
                         "glucose": pd.to_numeric(df[g_col], errors="coerce")}).dropna(subset=["time"])


# ------------------------------------------------------------------ validation

def validate_series(raw: pd.DataFrame, now: Optional[datetime] = None, source_format: str = "generic",
                    sensor_starts: Optional[List[datetime]] = None, until: Optional[datetime] = None) -> GlucoseSeries:
    raw = raw.sort_values("time").drop_duplicates("time")
    if until is not None:
        raw = raw[raw["time"] <= pd.Timestamp(until)]
    raw = raw[(raw["glucose"].isna()) | ((raw["glucose"] >= 20) & (raw["glucose"] <= 500))]
    if raw.empty:
        raise ValueError("no glucose readings")
    t0 = raw["time"].iloc[0].floor("5min")
    t1 = raw["time"].iloc[-1].ceil("5min")
    grid = pd.date_range(t0, t1, freq="5min")
    # align: nearest reading within 2.5 min of each grid point
    aligned = raw.set_index("time")["glucose"]
    aligned = aligned[~aligned.index.duplicated()]
    g = aligned.reindex(grid, method="nearest", tolerance=pd.Timedelta("2.5min")).to_numpy(dtype=float)
    missing = np.isnan(g)
    # rate-of-change artifacts (|dG/dt| > 4 mg/dL/min between consecutive valid points)
    artifact = np.zeros(len(g), dtype=bool)
    dg = np.diff(g)
    roc = np.abs(dg) / 5.0
    bad = np.where(~np.isnan(roc) & (roc > ARTIFACT_ROC_MGDL_PER_MIN))[0]
    for i in bad:
        artifact[i + 1] = True
        if i + 2 < len(artifact):
            artifact[i + 2] = True
    valid = ~missing & ~artifact
    # gaps: runs of missing points >= 3 (15 min)
    gaps: List[Dict[str, object]] = []
    i = 0
    n = len(g)
    while i < n:
        if missing[i]:
            j = i
            while j < n and missing[j]:
                j += 1
            if j - i >= 3:
                gaps.append({"start": grid[i].isoformat(), "end": grid[j - 1].isoformat(), "minutes": 5 * (j - i)})
            i = j
        else:
            i += 1
    # sensor age: from explicit starts, else infer from gaps >= 2 h (warm-up)
    if sensor_starts is None:
        sensor_starts = [grid[0].to_pydatetime()]
        for gp in gaps:
            if gp["minutes"] >= 120:
                sensor_starts.append(datetime.fromisoformat(gp["end"]))
    starts = np.array(sorted(pd.to_datetime(sensor_starts)), dtype="datetime64[ns]")
    grid_np = grid.to_numpy(dtype="datetime64[ns]")
    idx = np.searchsorted(starts, grid_np, side="right") - 1
    idx = np.clip(idx, 0, len(starts) - 1)
    age = (grid_np - starts[idx]).astype("timedelta64[m]").astype(float) / 1440.0
    # staleness and quality
    now = now or grid[-1].to_pydatetime()
    last_valid = grid[np.where(valid)[0][-1]].to_pydatetime() if valid.any() else grid[0].to_pydatetime()
    staleness = max((now - last_valid).total_seconds() / 60.0, 0.0)
    recent = valid[-288:] if len(valid) >= 288 else valid
    coverage_24h = float(np.mean(recent)) if len(recent) else 0.0
    coverage_all = float(np.mean(valid))
    artifact_rate = float(np.mean(artifact))
    stale_pen = float(np.clip(staleness / 60.0, 0.0, 1.0))
    quality = float(np.clip(0.5 * coverage_24h + 0.3 * coverage_all + 0.2 * (1 - 5 * artifact_rate) - 0.5 * stale_pen, 0.0, 1.0))
    return GlucoseSeries(times=grid, glucose=g, valid=valid, artifact=artifact, sensor_age_days=age, gaps=gaps,
                         staleness_min=float(staleness), data_quality=quality, source_format=source_format, n_raw=int(len(raw)))


def ingest_csv(path_or_text: Union[str, Path], now: Optional[datetime] = None, until: Optional[datetime] = None) -> GlucoseSeries:
    if isinstance(path_or_text, Path) or (isinstance(path_or_text, str) and len(path_or_text) < 512 and Path(path_or_text).exists()):
        text = Path(path_or_text).read_text(encoding="utf-8-sig")
    else:
        text = str(path_or_text)
    fmt = _detect_format(text)
    raw = {"dexcom": _parse_dexcom, "libre": _parse_libre, "generic": _parse_generic}[fmt](text)
    return validate_series(raw, now=now, source_format=fmt, until=until)


# ------------------------------------------------------------------ writers (for synthetic data)

def write_dexcom_csv(path: Path, times: pd.DatetimeIndex, glucose: np.ndarray) -> None:
    rows = []
    for i, (t, g) in enumerate(zip(times, glucose)):
        if np.isnan(g):
            continue
        rows.append({
            "Index": i + 1,
            "Timestamp (YYYY-MM-DDThh:mm:ss)": t.strftime("%Y-%m-%dT%H:%M:%S"),
            "Event Type": "EGV",
            "Event Subtype": "",
            "Patient Info": "",
            "Device Info": "GlucoPilot synthetic",
            "Source Device ID": "SYN-0001",
            "Glucose Value (mg/dL)": int(round(g)),
            "Insulin Value (u)": "",
            "Carb Value (grams)": "",
            "Duration (hh:mm:ss)": "",
            "Glucose Rate of Change (mg/dL/min)": "",
            "Transmitter Time (Long Integer)": "",
            "Transmitter ID": "SYN",
        })
    pd.DataFrame(rows).to_csv(path, index=False, lineterminator="\n")


def write_libre_csv(path: Path, times: pd.DatetimeIndex, glucose: np.ndarray) -> None:
    lines = ["Glucose Data,Generated by GlucoPilot synthetic,,,", "Patient report,,,,",
             "Device,Serial Number,Device Timestamp,Record Type,Historic Glucose mg/dL,Scan Glucose mg/dL"]
    for t, g in zip(times, glucose):
        if np.isnan(g):
            continue
        lines.append(f"FreeStyle Libre,SYN,{t.strftime('%m-%d-%Y %I:%M %p')},0,{int(round(g))},")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
