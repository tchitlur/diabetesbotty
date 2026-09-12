"""One place that turns a sensor series into what a chart may draw.

Every glucose series that reaches the frontend goes through `series_for_display`: gaps of up to
`max_gap_min` (dropouts, flagged points) are filled by linear interpolation, a short trailing gap
holds the last reading, and anything longer stays null and is listed in `gaps` so the chart can
draw a labelled break. Charts never do their own gap handling."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

MAX_GAP_MIN = 45


def _iso(t) -> str:
    if isinstance(t, str):
        return t[:16]
    if hasattr(t, "to_pydatetime"):
        t = t.to_pydatetime()
    return t.isoformat(timespec="minutes")


def series_for_display(times: Sequence[Any], values: Sequence[Any], valid: Optional[Sequence[bool]] = None,
                       step_min: int = 5, max_gap_min: int = MAX_GAP_MIN) -> Dict[str, Any]:
    """times: ISO strings or datetimes on a regular grid (step_min apart); values: numbers, None or NaN;
    valid: optional mask (False = treat as missing). Returns {times, raw, display, gaps}."""
    n = len(values)
    raw = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
    if valid is not None:
        raw = np.where(np.asarray(valid, dtype=bool), raw, np.nan)
    disp = raw.copy()
    gaps: List[Dict[str, Any]] = []
    iso = [_iso(t) for t in times]
    i = 0
    while i < n:
        if np.isnan(disp[i]):
            j = i
            while j < n and np.isnan(disp[j]):
                j += 1
            length = (j - i) * step_min
            if i > 0 and j < n and length <= max_gap_min:
                disp[i:j] = np.linspace(disp[i - 1], disp[j], j - i + 2)[1:-1]
            elif i > 0 and j == n and length <= max_gap_min:
                disp[i:j] = disp[i - 1]                       # trailing short gap: hold the last reading
            elif i == 0 and j < n and length <= max_gap_min:
                disp[i:j] = disp[j]                           # leading short gap: back-fill from the first reading
            else:
                gaps.append({"start": iso[i], "end": iso[min(j, n) - 1], "minutes": length})
            i = j
        else:
            i += 1
    return {"times": iso,
            "raw": [None if np.isnan(x) else round(float(x), 1) for x in raw],
            "display": [None if np.isnan(x) else round(float(x), 1) for x in disp],
            "gaps": gaps}


def display_values(times: Sequence[Any], values: Sequence[Any], valid: Optional[Sequence[bool]] = None, step_min: int = 5) -> List[Optional[float]]:
    """Just the continuous array."""
    return series_for_display(times, values, valid, step_min)["display"]
