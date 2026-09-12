"""Deterministic local parser (fallback for both Gemini parsers).

Regex + a ~55-item food/drink lookup table + keyword rules for actions.
Handles the required examples:
  "can I have two more beers tonight"
  "fasted run tomorrow at 7 for 30 min"
  "two shots of vodka at 11pm"
  "large coffee now"
  "can I lift for 45 min at 6pm"
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from backend.config import FOOD_TABLE_PATH
from backend.schema.events import Event
from backend.schema.api import ParsedEvent, EventModel

NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "couple": 2, "couple of": 2, "few": 3, "half": 0.5, "double": 2, "triple": 3}

AEROBIC = ["run", "running", "jog", "jogging", "cycle", "cycling", "bike", "biking", "swim", "swimming", "walk", "walking",
           "hike", "hiking", "row", "rowing", "elliptical", "cardio", "treadmill", "spin", "spinning"]
ANAEROBIC = ["lift", "lifting", "weights", "weight training", "strength", "gym session", "deadlift", "squat", "squats", "bench",
             "crossfit", "sprint", "sprints", "hiit"]
MIXED = ["soccer", "football", "basketball", "tennis", "hockey", "climbing", "boxing", "martial arts", "yoga", "pilates", "workout", "exercise", "train", "training", "gym"]
INTENSITY = {"easy": 0.4, "light": 0.4, "gentle": 0.35, "slow": 0.4, "moderate": 0.6, "brisk": 0.6, "hard": 0.8, "intense": 0.85, "fast": 0.8, "tempo": 0.75, "max": 0.95, "all out": 0.95}


@lru_cache(maxsize=1)
def food_table() -> Dict[str, Dict[str, Any]]:
    with open(FOOD_TABLE_PATH, "r", encoding="utf-8") as f:
        t = json.load(f)
    return {k: v for k, v in t.items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def alias_index() -> List[Tuple[str, str]]:
    """(alias, canonical) sorted longest-first so 'light beer' wins over 'beer'."""
    idx = []
    for name, row in food_table().items():
        idx.append((name, name))
        for a in row.get("aliases", []):
            idx.append((a, name))
    idx.sort(key=lambda t: -len(t[0]))
    return idx


def lookup_food(name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    n = name.lower().strip()
    for alias, canon in alias_index():
        if re.search(r"\b" + re.escape(alias) + r"\b", n):
            return canon, food_table()[canon]
    return None


# ------------------------------------------------------------------ time parsing

def parse_time(text: str, now: datetime) -> Tuple[datetime, str]:
    """Resolve when the event happens. Returns (datetime, how it was resolved)."""
    t = text.lower()
    base = now.replace(second=0, microsecond=0)
    day = base.replace(hour=0, minute=0)
    day_shift = 0
    if "tomorrow" in t:
        day_shift = 1
    elif "tonight" in t or "this evening" in t:
        day_shift = 0
    elif "yesterday" in t or "last night" in t:
        day_shift = -1
    m = re.search(r"\bin\s+(\d+|an?|half an?)\s*(hour|hours|hr|h|min|mins|minutes)\b", t)
    if m:
        n = m.group(1)
        qty = 0.5 if n.startswith("half") else (1.0 if n in ("a", "an") else float(n))
        mins = qty * 60 if m.group(2).startswith("h") else qty
        return base + timedelta(minutes=mins), "relative"
    m = re.search(r"\b(?:at|around|by|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b", t) or re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2) or 0)
        ap = (m.group(3) or "").replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        elif not ap:
            # no am/pm: "tonight at 11" -> 23; "tomorrow at 7" -> 07; otherwise the next occurrence
            if "tonight" in t or "evening" in t or "night" in t:
                h = h + 12 if h < 12 else h
            elif "morning" in t or "tomorrow" in t:
                pass
            elif h < 6:
                h += 12
        when = day + timedelta(days=day_shift, hours=h, minutes=mi)
        if day_shift == 0 and when < base - timedelta(minutes=30) and "tonight" not in t:
            when += timedelta(days=1)
        return when, "clock"
    if "tonight" in t or "this evening" in t:
        # already evening -> "tonight" means from now; earlier in the day -> 20:00
        when = day.replace(hour=20)
        return (base if base.hour >= 17 else when), "tonight"
    if "tomorrow" in t:
        if "morning" in t:
            return day + timedelta(days=1, hours=7), "tomorrow morning"
        if "evening" in t or "night" in t:
            return day + timedelta(days=1, hours=20), "tomorrow evening"
        return day + timedelta(days=1, hours=12), "tomorrow"
    if "this morning" in t:
        return day.replace(hour=8), "morning"
    if "lunch" in t:
        return day.replace(hour=12, minute=30) if base.hour < 12 else base, "lunch"
    if "dinner" in t:
        return day.replace(hour=19) if base.hour < 19 else base, "dinner"
    if "breakfast" in t:
        return day.replace(hour=7, minute=30) if base.hour < 8 else (day + timedelta(days=1, hours=7, minutes=30)), "breakfast"
    if "before bed" in t or "bedtime" in t:
        return day.replace(hour=23), "bedtime"
    return base, "now"


def parse_count(text: str, keyword: str) -> float:
    """Number preceding the keyword ('two more beers', '2 beers', 'a couple of shots')."""
    t = text.lower()
    pat = r"((?:\d+(?:\.\d+)?)|(?:" + "|".join(sorted(map(re.escape, NUMBER_WORDS), key=len, reverse=True)) + r"))\s+(?:more\s+|extra\s+|of\s+|large\s+|big\s+|small\s+|cold\s+)*" + re.escape(keyword)
    m = re.search(pat, t)
    if m:
        n = m.group(1)
        return float(n) if re.match(r"^\d", n) else float(NUMBER_WORDS[n])
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|\*)\s*" + re.escape(keyword), t)
    if m:
        return float(m.group(1))
    return 1.0


def parse_duration(text: str, default: float) -> float:
    t = text.lower()
    m = re.search(r"\bfor\s+(\d+(?:\.\d+)?|an?|half an?)\s*(hour|hours|hr|hrs|h|min|mins|minutes|m)\b", t) or \
        re.search(r"\b(\d+(?:\.\d+)?)\s*(hour|hours|hr|hrs|min|mins|minutes)\b", t)
    if m:
        n = m.group(1)
        qty = 0.5 if n.startswith("half") else (1.0 if n in ("a", "an") else float(n))
        return qty * 60 if m.group(2).startswith("h") else qty
    return default


def parse_grams(text: str, unit: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|grams?)\s*(?:of\s+)?" + unit, text.lower())
    return float(m.group(1)) if m else None


# ------------------------------------------------------------------ main

def parse_text_local(text: str, now: datetime) -> ParsedEvent:
    t = text.lower().strip()
    when, how = parse_time(t, now)
    notes: List[str] = [f"time resolved from '{how}'"]
    raw_items: List[Dict[str, Any]] = []
    # ---- exercise
    kind = None
    for kw in ANAEROBIC:
        if re.search(r"\b" + re.escape(kw) + r"\b", t):
            kind = "anaerobic"; break
    if kind is None:
        for kw in AEROBIC:
            if re.search(r"\b" + re.escape(kw) + r"\b", t):
                kind = "aerobic"; break
    if kind is None:
        for kw in MIXED:
            if re.search(r"\b" + re.escape(kw) + r"\b", t):
                kind = "mixed"; break
    if kind is not None and not any(w in t for w in ("beer", "wine", "coffee", "shot")):
        dur = parse_duration(t, 45.0 if kind == "anaerobic" else 30.0)
        inten = 0.6 if kind == "aerobic" else (0.7 if kind == "anaerobic" else 0.65)
        for w, v in INTENSITY.items():
            if re.search(r"\b" + re.escape(w) + r"\b", t):
                inten = v
        label = re.sub(r"\b(can|could|i|should|may|want to|to|please|ok|okay)\b", "", t).strip()
        fasted = "fasted" in t or "fasting" in t or "before breakfast" in t
        ev = Event(type="exercise", start_time=when.isoformat(timespec="minutes"), duration_min=dur, exercise_kind=kind,
                   intensity=inten, uncertainty=0.15, source="local", label=(("fasted " if fasted else "") + f"{kind} {int(dur)} min").strip())
        if fasted:
            notes.append("fasted: no carbs assumed before the session")
        return ParsedEvent(event=EventModel(**ev.to_dict()), parser="local", confidence=0.8, raw_items=[{"item": label, "kind": kind, "duration_min": dur}], notes="; ".join(notes))
    # ---- insulin
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:u|units?)\b", t)
    if m and ("insulin" in t or "bolus" in t or "units" in t or "unit" in t):
        units = float(m.group(1))
        kind_i = "basal" if ("basal" in t or "lantus" in t or "tresiba" in t or "long acting" in t) else "bolus"
        ev = Event(type="insulin", start_time=when.isoformat(timespec="minutes"), insulin_units=units, insulin_kind=kind_i, uncertainty=0.05, source="local", label=f"{units:g} U {kind_i}")
        return ParsedEvent(event=EventModel(**ev.to_dict()), parser="local", confidence=0.85, raw_items=[{"item": "insulin", "units": units}], notes="; ".join(notes))
    # ---- sleep / illness / stress / water
    m = re.search(r"slept\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:h|hours?)", t) or re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hours?)\s+(?:of\s+)?sleep", t)
    if m:
        h = float(m.group(1))
        ev = Event(type="sleep", start_time=(now.replace(hour=0, minute=0) - timedelta(hours=1)).isoformat(timespec="minutes"), duration_min=h * 60, sleep_hours=h, uncertainty=0.1, source="local", label=f"slept {h:g} h")
        return ParsedEvent(event=EventModel(**ev.to_dict()), parser="local", confidence=0.8, raw_items=[{"item": "sleep", "hours": h}], notes="; ".join(notes))
    if any(w in t for w in ("sick", "flu", "fever", "cold", "ill", "infection", "covid")) and "cold brew" not in t:
        sev = 0.7 if "fever" in t or "flu" in t else 0.5
        ev = Event(type="illness", start_time=when.isoformat(timespec="minutes"), duration_min=1440, severity=sev, uncertainty=0.3, source="local", label="illness")
        return ParsedEvent(event=EventModel(**ev.to_dict()), parser="local", confidence=0.6, raw_items=[{"item": "illness", "severity": sev}], notes="; ".join(notes))
    if any(w in t for w in ("stress", "stressed", "anxious", "exam", "deadline", "presentation")):
        ev = Event(type="stress", start_time=when.isoformat(timespec="minutes"), duration_min=480, severity=0.6, uncertainty=0.3, source="local", label="stress")
        return ParsedEvent(event=EventModel(**ev.to_dict()), parser="local", confidence=0.6, raw_items=[{"item": "stress", "severity": 0.6}], notes="; ".join(notes))
    # ---- food / drink / caffeine via the table (longest alias first; may combine several items)
    found: List[Tuple[str, Dict[str, Any], float]] = []
    remaining = t
    for alias, canon in alias_index():
        if re.search(r"\b" + re.escape(alias) + r"\b", remaining):
            remaining = re.sub(r"\b" + re.escape(alias) + r"\b", " ", remaining)
            if any(f[0] == canon for f in found):
                continue  # 'two shots of vodka': 'vodka' is the same row as 'shots'
            if canon == "water" and any(f[0] != "water" for f in found):
                continue
            count = parse_count(t, alias)
            found.append((canon, food_table()[canon], count))
    if not found:
        ev = Event(type="meal", start_time=when.isoformat(timespec="minutes"), duration_min=15, carbs_g=45, fat_g=15, protein_g=20, fiber_g=3, uncertainty=0.5, source="local", label=text.strip()[:40] or "unrecognised meal")
        return ParsedEvent(event=EventModel(**ev.to_dict()), parser="local", confidence=0.3, raw_items=[{"item": text, "note": "not in table; generic meal assumed"}], notes="; ".join(notes + ["no table match: generic 45 g meal"]))
    kinds = [f[1]["kind"] for f in found]
    if "alcohol" in kinds:
        etype = "alcohol"
    elif "caffeine" in kinds:
        etype = "caffeine"
    elif kinds == ["water"]:
        etype = "water"
    else:
        etype = "meal"
    tot = {"carbs_g": 0.0, "fat_g": 0.0, "protein_g": 0.0, "fiber_g": 0.0, "alcohol_g": 0.0, "caffeine_mg": 0.0, "water_ml": 0.0}
    labels = []
    for canon, row, count in found:
        if "large" in t and canon == "coffee":
            row = food_table()["large coffee"]; canon = "large coffee"
        for k in tot:
            tot[k] += float(row.get(k, 0.0)) * count
        labels.append(f"{count:g} {canon}" if count != 1 else canon)
        raw_items.append({"item": canon, "count": count, "serving": row.get("serving"), **{k: row.get(k, 0) for k in ("carbs_g", "fat_g", "protein_g", "alcohol_g", "caffeine_mg")}})
    n_drinks = tot["alcohol_g"] / 14.0
    dur = parse_duration(t, 0.0)
    if etype == "alcohol" and dur == 0.0:
        dur = float(min(30 + 30 * n_drinks, 240))
    if etype == "meal" and dur == 0.0:
        dur = 15.0
    ev = Event(type=etype, start_time=when.isoformat(timespec="minutes"), duration_min=dur, carbs_g=tot["carbs_g"], fat_g=tot["fat_g"],
               protein_g=tot["protein_g"], fiber_g=tot["fiber_g"], alcohol_g=tot["alcohol_g"], caffeine_mg=tot["caffeine_mg"],
               water_ml=tot["water_ml"], uncertainty=0.25 if etype != "meal" else 0.35, source="local", label=", ".join(labels))
    conf = 0.75 if len(found) == 1 else 0.65
    return ParsedEvent(event=EventModel(**ev.to_dict()), parser="local", confidence=conf, raw_items=raw_items, notes="; ".join(notes))


def parse_image_local(filename: str, now: datetime, hint: str = "") -> ParsedEvent:
    """Without vision the fallback can only use the file name / caption."""
    text = (hint + " " + re.sub(r"[_\-.]", " ", filename)).strip()
    pe = parse_text_local(text or "meal", now)
    pe.event.uncertainty = max(pe.event.uncertainty, 0.5)
    pe.confidence = min(pe.confidence, 0.4)
    pe.notes = "no vision model available; estimate from file name/caption only. " + pe.notes
    return pe
