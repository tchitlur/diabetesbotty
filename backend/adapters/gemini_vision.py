"""Gemini vision parser: photo -> items with portion estimates -> macros with
per-item uncertainty, cross-checked against food_table.json."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from backend.schema.events import Event
from backend.schema.api import ParsedEvent, EventModel
from backend.adapters.gemini_common import generate, extract_json, cross_check_items

PROMPT = """You are estimating nutrition from a photo for a person with type 1 diabetes. Identify every food and drink item,
estimate the portion, and give macros for that portion. Return ONLY a JSON object, no prose, no code fences:
{{
  "items": [
    {{"name": "<short generic name, e.g. pizza, beer, rice>", "portion": "<e.g. 2 slices, 12 oz, 1 cup>", "count": <number of servings as a number>,
     "carbs_g": <number>, "fat_g": <number>, "protein_g": <number>, "fiber_g": <number>, "alcohol_g": <number>, "caffeine_mg": <number>,
     "uncertainty": <0-1 fractional uncertainty of your estimate>}}
  ],
  "label": "<short meal label>",
  "confidence": <0-1 that the items are identified correctly>,
  "notes": "<short string>"
}}
Use grams. One standard alcoholic drink = 14 g alcohol. If the photo is not food or drink, return {{"items": [], "label": "not food", "confidence": 0, "notes": "..."}}.
{hint}"""


def parse_image_gemini(data: bytes, mime: str, now: datetime, hint: str = "") -> ParsedEvent:
    from google.genai import types
    part = types.Part.from_bytes(data=data, mime_type=mime or "image/jpeg")
    prompt = PROMPT.format(hint=(f"The person added this caption: {hint}" if hint else ""))
    raw = generate([part, prompt])
    obj = extract_json(raw)
    items: List[Dict[str, Any]] = obj.get("items") or []
    if not items:
        raise ValueError("no items identified")
    totals, raw_items, notes = cross_check_items(items)
    if totals["alcohol_g"] > 0:
        etype = "alcohol"
    elif totals["caffeine_mg"] > 0 and totals["carbs_g"] < 10:
        etype = "caffeine"
    else:
        etype = "meal"
    uncs = [float(i.get("uncertainty") or 0.3) for i in items]
    unc = sum(uncs) / len(uncs)
    dur = 15.0 if etype == "meal" else (60.0 if etype == "alcohol" else 0.0)
    ev = Event(type=etype, start_time=now.isoformat(timespec="minutes"), duration_min=dur, carbs_g=totals["carbs_g"], fat_g=totals["fat_g"],
               protein_g=totals["protein_g"], fiber_g=totals["fiber_g"], alcohol_g=totals["alcohol_g"], caffeine_mg=totals["caffeine_mg"],
               uncertainty=max(0.1, min(unc, 0.8)), source="gemini", label=str(obj.get("label") or "photo meal")[:60])
    try:
        conf = float(obj.get("confidence", 0.6))
    except (TypeError, ValueError):
        conf = 0.6
    notes = [str(obj.get("notes") or "")] + notes
    return ParsedEvent(event=EventModel(**ev.to_dict()), parser="gemini", confidence=max(0.0, min(conf, 1.0)), raw_items=raw_items,
                       notes="; ".join(n for n in notes if n))
