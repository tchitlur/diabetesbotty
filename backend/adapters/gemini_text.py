"""Gemini text parser: free text -> Event + confidence (JSON only)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from backend.schema.api import ParsedEvent, EventModel
from backend.adapters.gemini_common import generate, extract_json, to_event, cross_check_items

PROMPT = """You convert one message from a person with type 1 diabetes into ONE structured event for a physiology simulator.
Return ONLY a JSON object. No prose, no markdown, no code fences.

Keys (all required; use 0 or null when not applicable):
  type: one of meal | insulin | alcohol | caffeine | exercise | sleep | illness | stress | water
  start_time: ISO 8601 local datetime like 2025-08-29T21:00 (resolve "tonight", "tomorrow at 7", "at 6pm", "now", "in 2 hours")
  duration_min: number (exercise/drinking sessions/sleep); 0 if instantaneous
  carbs_g, fat_g, protein_g, fiber_g: grams for meals AND for drinks (beer 12 oz = 13 g carbs, wine 5 oz = 4 g, spirits 0 g)
  alcohol_g: grams of ethanol (one standard drink = 14 g; a shot, a 12 oz beer, a 5 oz glass of wine are each one drink)
  caffeine_mg: coffee 8 oz = 95 mg, large/16 oz = 190 mg, espresso shot = 63 mg, tea = 45 mg, energy drink = 160 mg
  insulin_units: units; insulin_kind: bolus | basal | null
  exercise_kind: aerobic (run, cycle, swim, walk) | anaerobic (lifting, sprints, HIIT) | mixed (team sports) | null
  intensity: 0-1 (easy 0.4, moderate 0.6, hard 0.8)
  sleep_hours, severity (0-1 for illness/stress), water_ml
  uncertainty: fractional uncertainty of the amounts (0.1 precise, 0.3 typical, 0.5 vague)
  label: short human label like "2 beers" or "fasted run 30 min"
  confidence: 0-1 that this event is what the person meant
  items: list of {{name, count, serving}} for foods/drinks mentioned (empty list otherwise)
  notes: short string (e.g. "fasted", "question about permission")

Rules: "two more beers" means 2 beers (the word "more" is not a quantity). If the message is a question ("can I ...")
still produce the proposed event. If it is already evening, "tonight" starts now. A "fasted" workout means no carbs before it.
Current local time: {now} ({weekday}).

Message: {text}"""


def parse_text_gemini(text: str, now: datetime) -> ParsedEvent:
    prompt = PROMPT.format(now=now.isoformat(timespec="minutes"), weekday=now.strftime("%A"), text=text.strip())
    raw = generate([prompt])
    obj = extract_json(raw)
    ev = to_event(obj, now)
    # a proposal resolved to a time already past (e.g. "at 6pm" asked at 19:00) means the next occurrence
    past_tense = any(w in text.lower() for w in ("yesterday", "last night", "slept", "ate ", "had ", "drank", "this morning"))
    if ev.type in ("exercise", "alcohol", "caffeine", "meal") and not past_tense and ev.start < now - timedelta(minutes=30):
        ev = ev.copy(start_time=(ev.start + timedelta(days=1)).isoformat(timespec="minutes"))
        notes_extra = "time was in the past; moved to the next day"
    else:
        notes_extra = ""
    items = obj.get("items") or []
    notes = [str(obj.get("notes") or ""), notes_extra]
    raw_items = []
    if items and ev.type in ("meal", "alcohol", "caffeine"):
        totals, raw_items, xnotes = cross_check_items(items)
        notes += xnotes
        # the per-item table check is authoritative for the amounts when any item matched the table
        if any(str(i.get("source", "")).startswith("table") for i in raw_items):
            for k, v in totals.items():
                if v > 0:
                    setattr(ev, k, float(v))
    try:
        conf = float(obj.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    return ParsedEvent(event=EventModel(**ev.to_dict()), parser="gemini", confidence=max(0.0, min(conf, 1.0)),
                       raw_items=raw_items, notes="; ".join(n for n in notes if n))
