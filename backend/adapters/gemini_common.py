"""Shared Gemini plumbing: client, JSON extraction, event validation and the
food-table cross-check. The API key is read from config and never logged."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.config import GEMINI_MODEL, gemini_api_key
from backend.schema.events import Event, EVENT_TYPES
from backend.adapters.local_parser import lookup_food

_CLIENT = None


def client():
    """Lazily construct the google-genai client. Raises if no key."""
    global _CLIENT
    if _CLIENT is None:
        key = gemini_api_key()
        if not key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        from google import genai
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def generate(contents: List[Any], temperature: float = 0.1, timeout_s: float = 20.0) -> str:
    """One generate_content call returning the raw text. Isolated so tests can monkeypatch it."""
    from google.genai import types
    resp = client().models.generate_content(
        model=GEMINI_MODEL, contents=contents,
        config=types.GenerateContentConfig(temperature=temperature, response_mime_type="application/json",
                                           http_options=types.HttpOptions(timeout=int(timeout_s * 1000))))
    return resp.text or ""


def extract_json(text: str) -> Dict[str, Any]:
    """Strip code fences / prose defensively and parse the first JSON object."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.DOTALL)
        if not m:
            raise
        obj = json.loads(m.group(0))
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        obj = obj[0]
    if not isinstance(obj, dict):
        raise ValueError("Gemini returned non-object JSON")
    return obj


NUMERIC = ["duration_min", "carbs_g", "fat_g", "protein_g", "fiber_g", "alcohol_g", "caffeine_mg", "insulin_units",
           "intensity", "sleep_hours", "severity", "water_ml", "uncertainty"]


def to_event(obj: Dict[str, Any], now: datetime, source: str = "gemini") -> Event:
    """Coerce a Gemini JSON object into a validated Event (raises on bad enums)."""
    d: Dict[str, Any] = {"source": source}
    et = str(obj.get("type", "meal")).lower().strip()
    if et not in EVENT_TYPES:
        raise ValueError(f"bad event type {et!r}")
    d["type"] = et
    st = obj.get("start_time") or now.isoformat(timespec="minutes")
    try:
        d["start_time"] = datetime.fromisoformat(str(st).replace("Z", "")).replace(tzinfo=None).isoformat(timespec="minutes")
    except ValueError:
        d["start_time"] = now.isoformat(timespec="minutes")
    for k in NUMERIC:
        v = obj.get(k)
        try:
            d[k] = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            d[k] = 0.0
    if d["uncertainty"] <= 0:
        d["uncertainty"] = 0.3
    ik = obj.get("insulin_kind")
    d["insulin_kind"] = str(ik).lower() if ik in ("bolus", "basal") else (None if et != "insulin" else "bolus")
    ek = obj.get("exercise_kind")
    d["exercise_kind"] = str(ek).lower() if ek in ("aerobic", "anaerobic", "mixed") else (None if et != "exercise" else "aerobic")
    d["label"] = str(obj.get("label") or "")[:60]
    return Event.from_dict(d)


def cross_check_items(items: List[Dict[str, Any]]) -> Tuple[Dict[str, float], List[Dict[str, Any]], List[str]]:
    """For each item Gemini returned, if the name matches the food table use
    the table's per-serving macros x count (Gemini's portion estimate is kept
    when it is within 40 % of the table); otherwise trust Gemini's numbers."""
    totals = {k: 0.0 for k in ("carbs_g", "fat_g", "protein_g", "fiber_g", "alcohol_g", "caffeine_mg", "water_ml")}
    out_items: List[Dict[str, Any]] = []
    notes: List[str] = []
    for it in items or []:
        name = str(it.get("name") or it.get("item") or "").strip()
        try:
            count = float(it.get("count") or 1.0)
        except (TypeError, ValueError):
            count = 1.0
        g = {k: float(it.get(k) or 0.0) for k in totals}
        hit = lookup_food(name) if name else None
        used = "gemini"
        if hit:
            canon, row = hit
            table = {k: float(row.get(k, 0.0)) * count for k in totals}
            major = "carbs_g" if row["kind"] in ("meal",) else ("alcohol_g" if row["kind"] == "alcohol" else ("caffeine_mg" if row["kind"] == "caffeine" else "water_ml"))
            gv, tv = g[major], table[major]
            if tv > 0 and (gv <= 0 or abs(gv - tv) / tv > 0.4):
                g = table
                used = f"table:{canon}"
                notes.append(f"{name}: used table value for {canon} ({tv:.0f} {major})")
            else:
                used = f"gemini (checked vs {canon})"
        for k in totals:
            totals[k] += g[k]
        out_items.append({"item": name, "count": count, "portion": it.get("portion") or it.get("serving"), "uncertainty": it.get("uncertainty", 0.3), "source": used, **{k: round(g[k], 1) for k in totals if g[k]}})
    return totals, out_items, notes
