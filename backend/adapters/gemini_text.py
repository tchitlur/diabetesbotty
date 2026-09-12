"""Gemini text parser: free text -> Event + confidence (JSON only)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from backend.schema.api import ParsedEvent, EventModel
from backend.adapters.gemini_common import generate, extract_json, to_event, cross_check_items
from backend.adapters.local_parser import lookup_food, parse_count

PROMPT = """You convert one message from a person with type 1 diabetes into ONE structured event for a physiology simulator.
Return ONLY a JSON object. No prose, no markdown, no code fences.

Event schema (every key required; use 0, null or [] when not applicable):
{{
  "type": "meal | insulin | alcohol | caffeine | exercise | sleep | illness | stress | water",
  "start_time": "ISO 8601 local datetime, e.g. 2025-08-29T21:00",
  "duration_min": number,          // exercise / drinking session / sleep; 0 if instantaneous; meals 15
  "carbs_g": number, "fat_g": number, "protein_g": number, "fiber_g": number,   // grams, for meals AND drinks
  "alcohol_g": number,             // grams of ethanol; one standard drink = 14 g
  "caffeine_mg": number,
  "insulin_units": number, "insulin_kind": "bolus | basal | null",
  "exercise_kind": "aerobic | anaerobic | mixed | null", "intensity": number,   // 0-1
  "sleep_hours": number, "severity": number, "water_ml": number,
  "uncertainty": number,           // fractional uncertainty of the amounts: 0.1 precise, 0.3 typical, 0.5 vague
  "label": "short human label", "confidence": number,
  "items": [{{"name": "...", "count": number, "serving": "..."}}], "notes": "short string"
}}

Estimating food: give realistic macros for the named food and portion, as a dietitian would. Different foods must
get different numbers; never reuse a default. Reference values per serving: pizza slice 36 g carbs / 10 g fat / 12 g protein;
small green salad 8 g carbs / 8 g fat / 3 g protein; burger with bun 45/25/25; bowl of pasta 70/12/15; sandwich 40/12/20;
bowl of rice 45/1/4; banana 27/0/1; ice cream scoop 20/8/3; slice of cake 45/15/5; 12 oz beer 13 g carbs + 14 g alcohol;
5 oz wine 4 g carbs + 14 g alcohol; a shot 0 g carbs + 14 g alcohol; coffee 8 oz 95 mg caffeine, large / 16 oz 190 mg,
espresso shot 63 mg, tea 45 mg, energy drink 160 mg. "Two coffees" = 2 x the size. Exercise: aerobic = run, cycle, swim,
walk (intensity easy 0.4, moderate 0.6, hard 0.8); anaerobic = lifting, sprints, HIIT (0.7); mixed = team sports (0.65).

Worked examples (current time 2025-08-29T19:00, Friday):
"can I have pizza for dinner?" -> {{"type":"meal","start_time":"2025-08-29T19:00","duration_min":15,"carbs_g":72,"fat_g":20,"protein_g":24,"fiber_g":4,"alcohol_g":0,"caffeine_mg":0,"insulin_units":0,"insulin_kind":null,"exercise_kind":null,"intensity":0,"sleep_hours":0,"severity":0,"water_ml":0,"uncertainty":0.3,"label":"pizza, 2 slices","confidence":0.8,"items":[{{"name":"pizza","count":2,"serving":"slice"}}],"notes":"question about permission; 2 slices assumed"}}
"can I have a small salad for dinner?" -> {{"type":"meal","start_time":"2025-08-29T19:00","duration_min":15,"carbs_g":8,"fat_g":8,"protein_g":3,"fiber_g":3,"alcohol_g":0,"caffeine_mg":0,"insulin_units":0,"insulin_kind":null,"exercise_kind":null,"intensity":0,"sleep_hours":0,"severity":0,"water_ml":0,"uncertainty":0.3,"label":"small salad","confidence":0.8,"items":[{{"name":"salad","count":1,"serving":"small bowl"}}],"notes":"question about permission"}}
"large coffee now" -> {{"type":"caffeine","start_time":"2025-08-29T19:00","duration_min":0,"carbs_g":0,"fat_g":0,"protein_g":0,"fiber_g":0,"alcohol_g":0,"caffeine_mg":190,"insulin_units":0,"insulin_kind":null,"exercise_kind":null,"intensity":0,"sleep_hours":0,"severity":0,"water_ml":0,"uncertainty":0.15,"label":"large coffee","confidence":0.9,"items":[{{"name":"coffee","count":1,"serving":"16 oz"}}],"notes":""}}
"run at 7 tomorrow for 30 min" -> {{"type":"exercise","start_time":"2025-08-30T07:00","duration_min":30,"carbs_g":0,"fat_g":0,"protein_g":0,"fiber_g":0,"alcohol_g":0,"caffeine_mg":0,"insulin_units":0,"insulin_kind":null,"exercise_kind":"aerobic","intensity":0.6,"sleep_hours":0,"severity":0,"water_ml":0,"uncertainty":0.15,"label":"run 30 min","confidence":0.9,"items":[],"notes":""}}
"can I have two more beers tonight?" -> {{"type":"alcohol","start_time":"2025-08-29T19:00","duration_min":90,"carbs_g":26,"fat_g":0,"protein_g":0,"fiber_g":0,"alcohol_g":28,"caffeine_mg":0,"insulin_units":0,"insulin_kind":null,"exercise_kind":null,"intensity":0,"sleep_hours":0,"severity":0,"water_ml":0,"uncertainty":0.2,"label":"2 beers","confidence":0.85,"items":[{{"name":"beer","count":2,"serving":"12 oz"}}],"notes":"question about permission"}}

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
    # the whole message against the food table: "large coffee", "two more beers" carry a size Gemini may drop
    hit = lookup_food(text)
    if hit:
        canon, row = hit
        key = {"caffeine": "caffeine_mg", "alcohol": "alcohol_g"}.get(row.get("kind"))
        if key and ev.type == row.get("kind"):
            count = max(1.0, parse_count(text.lower(), canon.split()[-1]))
            table_v = float(row.get(key, 0.0)) * count
            cur = float(getattr(ev, key) or 0.0)
            if table_v > 0 and (cur <= 0 or abs(cur - table_v) / table_v > 0.4):
                setattr(ev, key, table_v)
                if row.get("kind") == "alcohol" and row.get("carbs_g"):
                    ev.carbs_g = float(row["carbs_g"]) * count
                notes.append(f"size from the food table: {canon} x{count:g}")
    try:
        conf = float(obj.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    return ParsedEvent(event=EventModel(**ev.to_dict()), parser="gemini", confidence=max(0.0, min(conf, 1.0)),
                       raw_items=raw_items, notes="; ".join(n for n in notes if n))
