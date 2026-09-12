"""The chat router: Gemini chooses among the backend tools (function calling) and phrases their
results; a keyword classifier does the same without a key. Either way every number in the
answer is checked against the tool results, and an answer that fails is replaced by a
templated one built from the results (the violation is logged)."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.config import GEMINI_MODEL, gemini_available
from backend.chat import tools as T
from backend.chat import phrase
from backend.decision.plain import fmt12, fmt_date
from backend.adapters.local_parser import parse_time

log = logging.getLogger("glucopilot.chat")

MAX_ROUNDS = 3
HISTORY_TURNS = 10
CLINICAL_CONSTANTS = {54.0, 70.0, 180.0, 250.0}   # thresholds the tools themselves use

SYSTEM = """You are the chat interface to a physiological model (a "digital twin") of one person with type 1 diabetes.
You answer only by calling the tools and phrasing what they return. Rules:
- Choose the tools that answer the question; you may call several, and call again if the first result needs a follow-up.
- Never state a number (glucose, grams, units, percentages, minutes, times) that did not come from a tool result. Copy numbers exactly as the tool gave them; do not compute new ones.
- Statements about what the person already DID ("I just ate", "I had a coffee 20 minutes ago", "just finished a run") are logs: call log_event. Proposals and permission questions ("can I", "should I", "is it okay", a food or workout at a future time) go to evaluate_action. A bare food, drink or workout with "now" or a future time and no past-tense verb ("large coffee now", "two coffees now", "lift weights now for 45 min") is a proposal: evaluate_action, never log_event; only past tense or "just" / "ago" is a log. "What if" hypotheticals go to whatif. "Why" questions about right now go to explain_now (pass mentioned_meal_minutes_ago when they say they ate N minutes ago).
- Times: the tools return ISO datetimes and *_text fields in 12-hour form; use the *_text form ("7:30 pm"). Today is {date}; now is {now}. For query_history build start/end as ISO local datetimes (e.g. yesterday = {yesterday}T00:00 to {today}T00:00; this week = the last 7 days; "at 3 pm" = a 10-minute window).
- A bare hour with no am/pm: for a workout, breakfast or coffee "at 7 tomorrow" means 7:00 am; "tonight at 9" means 9:00 pm; a dinner "at 7" means 7:00 pm. "Two coffees" is one caffeine event of 190 mg.
- If the question needs data no tool provides, say exactly what is missing instead of guessing.
- If it is a general question about type 1 diabetes and not about this person, answer briefly from general knowledge and say that it is general information.
- Answer in at most three short sentences, plain language, no markdown, no lists. Do not repeat series or arrays."""

# result keys that are long arrays (the card gets them; Gemini does not need them)
SERIES_KEYS = {"times", "median", "p10", "p90", "series", "mini_curve", "variants", "timeline", "energy_times", "energy_curve", "glucose_times",
               "glucose_median", "glucose_p10", "glucose_p90", "placed_events", "card", "diff", "organ_risk_baseline", "organ_risk_change", "week_summary", "tiles"}


def _compact(obj: Any, depth: int = 0) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in SERIES_KEYS and depth <= 1:
                if k == "tiles":
                    out[k] = [{"label": t["label"], "value_text": t["value_text"], "status": t["status"]} for t in v]
                continue
            out[k] = _compact(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_compact(x, depth + 1) for x in obj[:40]]
    return obj


# ------------------------------------------------------------------ grounding

_NUM = re.compile(r"(?<![\w.:])[-+]?\d+(?:\.\d+)?(?![\w:])")
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s?(am|pm)\b", re.IGNORECASE)
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?")


def _collect(obj: Any, nums: set, times: set) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        v = float(obj)
        nums.add(v)
        if 0 < v <= 1:
            nums.add(round(100 * v))       # fractions may be quoted as percentages
        return
    if isinstance(obj, str):
        for m in _ISO.finditer(obj):
            if "T" in m.group(0):
                times.add(fmt12(m.group(0)).lower())
        for m in _TIME.finditer(obj):
            times.add(f"{int(m.group(1))}:{m.group(2)} {m.group(3).lower()}")
        for m in _NUM.finditer(_TIME.sub(" ", _ISO.sub(" ", obj))):
            nums.add(float(m.group(0)))
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _collect(v, nums, times)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, nums, times)


def check_grounding(answer: str, results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]], user_text: str) -> List[str]:
    """Every number and clock time in `answer` must appear in a tool result (within rounding), in
    the tool arguments, in the person's own message, or be one of the clinical thresholds."""
    nums, times = set(CLINICAL_CONSTANTS), set()
    for _, args, res in results:
        _collect(res, nums, times)
        _collect(args, nums, times)
    _collect(user_text, nums, times)
    bad: List[str] = []
    for m in _TIME.finditer(answer):
        t = f"{int(m.group(1))}:{m.group(2)} {m.group(3).lower()}"
        if t not in times:
            bad.append(t)
    rest = _TIME.sub(" ", _ISO.sub(" ", answer))
    rest = re.sub(r"\b(\d+)\s*-\s*(\d+)\b", r"\1 \2", rest)     # ranges "70-180"
    for m in _NUM.finditer(rest):
        v = float(m.group(0))
        tol = 0.5 if abs(v) >= 10 else 0.051
        if not any(abs(v - a) <= tol for a in nums):
            bad.append(m.group(0))
    return bad


# ------------------------------------------------------------------ local classifier

FOCUS = [("insulin", r"\binsulin\b|\bunits?\b|\biob\b|on board"), ("carbs", r"\bcarb|digest|absorb"), ("energy", r"\benergy\b"), ("ketones", r"\bketone"),
         ("liver", r"\bliver\b|glycogen"), ("recovery", r"\brecover|\btired\b"), ("caffeine", r"\bcaffeine\b|\bcoffee\b"), ("alcohol", r"\balcohol\b|\bbac\b|\bdrunk\b")]
GENERAL_Q = re.compile(r"^(what is|what's|what are|define|explain what|what does .* mean)\b")
PAST = re.compile(r"^(i\s+)?(just|had|ate|drank|took|finished|did|went|ran|walked|lifted|injected|dosed|logged)\b|\bago\b")
QUESTION = re.compile(r"\b(why|what|how|when|will|can|could|should|is|am|are|do|does|did)\b|\?")
PERMISSION = re.compile(r"\b(can i|could i|should i|may i|is it (ok|okay|safe|fine)|okay to|ok to|allowed|safe to|want to|planning|gonna|going to have|for (dinner|lunch|breakfast|dessert))\b")
HISTORY = re.compile(r"\b(yesterday|last night|last week|this week|past week|this morning|earlier|last low|lows|average|mean|time in range|was my|were my|did i|how much sleep|slept|sleep last|at \d{1,2}(:\d{2})?\s?(am|pm)|history|so far today)\b")
FORECAST = re.compile(r"\b(will|going to|in \d+\s*(hours?|hrs?|h|minutes?|min)|tonight|overnight|by (bedtime|bed|morning|tomorrow)|later|forecast|predict|expect|next few hours|end up)\b")
WHY = re.compile(r"\bwhy\b|how come|what('s| is) (pushing|driving|causing|making)|not rising|isn't rising|not going up|still active|still working|on board|still digesting|left to digest|still in my (system|gut)")
NOW = re.compile(r"\b(glucose|sugar|bg|level|trend|going (up|down)|rising|falling|dropping|right now|currently|current|at the moment|how am i|status|energy|ketone|liver|recovery|caffeine|alcohol|carbs)\b")
COMPARE = re.compile(r"average person|compared to (the )?average|typical person|other people|most people")


def _minutes_ago(t: str) -> Optional[float]:
    m = re.search(r"(\d+)\s*(min|mins|minutes|hour|hours|hr|hrs|h)\b\s*ago", t) or re.search(r"(\d+)\s*(min|mins|minutes|hour|hours|hr|hrs|h)\s+ago", t)
    if not m:
        m2 = re.search(r"(an?|one|half an?)\s+(hour|hr)\s+ago", t)
        if m2:
            return 30.0 if m2.group(1).startswith("half") else 60.0
        return None
    n = float(m.group(1))
    return n * 60 if m.group(2).startswith("h") else n


def _history_window(t: str, now: datetime) -> Tuple[datetime, datetime, str]:
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    metric = "glucose"
    if re.search(r"\bsleep|slept\b", t):
        metric = "sleep"
    elif re.search(r"\blows?\b|hypo", t):
        metric = "lows"
    elif re.search(r"average|mean|time in range|\btir\b", t):
        metric = "average"
    elif re.search(r"\b(eat|ate|eaten|food|meals?)\b", t):
        metric = "carbs" if re.search(r"how many carbs|carbs did|total carbs", t) else "events"
    elif re.search(r"\bcarbs?\b", t):
        metric = "carbs"
    elif re.search(r"\binsulin\b|\bunits?\b|bolus", t):
        metric = "insulin"
    elif re.search(r"exercise|workout|\brun\b|\bran\b|training", t):
        metric = "exercise"
    elif re.search(r"coffee|caffeine", t):
        metric = "caffeine"
    elif re.search(r"drink|beer|wine|alcohol", t):
        metric = "alcohol"
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s?(am|pm)?\b", t)
    if m and metric == "glucose":
        when, _ = parse_time(t, now)
        if when > now:
            when -= timedelta(days=1)
        return when, when + timedelta(minutes=10), metric
    if "yesterday" in t:
        return day0 - timedelta(days=1), day0, metric
    if "last night" in t:
        return day0 - timedelta(hours=4), min(day0 + timedelta(hours=10), now), metric
    if re.search(r"this morning", t):
        return day0 + timedelta(hours=5), min(day0 + timedelta(hours=12), now), metric
    if re.search(r"week", t):
        return now - timedelta(days=7), now, metric
    if re.search(r"today|so far", t):
        return day0, now, metric
    if metric == "lows" and "last" in t:
        return now - timedelta(days=30), now, metric
    if metric == "sleep":
        return day0 - timedelta(hours=4), min(day0 + timedelta(hours=10), now), metric
    return now - timedelta(hours=24), now, metric


def _forecast_hours(t: str, now: datetime) -> float:
    m = re.search(r"in\s+(\d+)\s*(hours?|hrs?|h)\b", t)
    if m:
        return float(m.group(1))
    m = re.search(r"in\s+(\d+)\s*(minutes?|mins?|min)\b", t)
    if m:
        return max(float(m.group(1)) / 60.0, 1.0)
    if re.search(r"tonight|overnight|by (bed|bedtime|morning|tomorrow)|while i sleep", t):
        morning = (now + timedelta(days=1)).replace(hour=8, minute=0)
        return min(max((morning - now).total_seconds() / 3600.0, 2.0), 16.0)
    return 4.0


def _clean_log_text(t: str) -> str:
    t = re.sub(r"^(i\s+)?(just\s+)?(had|ate|drank|took|finished|did|went for|went|logged)\s+", "", t)
    t = re.sub(r"\b(\d+|an?|one|half an?)\s*(min|mins|minutes|hour|hours|hr|hrs|h)\s+ago\b", "", t)
    t = re.sub(r"\bjust\s+(finished|did|had)\b", "", t)
    return t.strip() or t


def classify_local(text: str, twin) -> Tuple[Optional[str], Dict[str, Any], Optional[str], Optional[str]]:
    """(tool name or None, args, focus, direct answer). The rules mirror the system prompt."""
    t = text.strip().lower()
    now = twin.now
    if t.startswith("/plan"):
        m = re.search(r"(\d+)\s*drink", t)
        return "plan_day", {"date": "tomorrow", "drinks": int(m.group(1)) if m else 0}, None, None
    if t.startswith("/change"):
        parts = t.split()
        return "change_lifestyle", {"name": parts[1] if len(parts) > 1 else "no_change"}, None, None
    if t.startswith("/why"):
        if twin.last_card is not None and twin.last_card.plain:
            return None, {}, None, f"{twin.last_card.plain.get('headline', '')}. {twin.last_card.plain.get('reason', '')}"
        return None, {}, None, "Nothing to explain yet. Ask about something first."
    if COMPARE.search(t):
        return "compare_to_average", {}, None, None
    if GENERAL_Q.search(t) and not re.search(r"\bmy\b|\bi\b", t):
        g = phrase.general(t)
        if g:
            return None, {}, None, g
    if re.search(r"^what if\b|^what happens if\b|^if i\b|what would happen", t):
        skip = None
        m = re.search(r"\b(skip|skipped|don'?t eat|no|miss|without)\s+(dinner|lunch|breakfast|supper|the next meal|my next meal|bolus|insulin)", t)
        if m:
            skip = {"supper": "dinner", "the next meal": "meal", "my next meal": "meal", "insulin": "bolus"}.get(m.group(2), m.group(2))
        args: Dict[str, Any] = {"skip": skip} if skip else {"text": re.sub(r"^(what if|what happens if|if)\s+i\s+(have|had|drink|drank|eat|ate|do|did|take|took|get)\s+", "", t)}
        return "whatif", args, None, None
    if WHY.search(t):
        mins = _minutes_ago(t)
        args = {}
        if mins is not None and re.search(r"\b(ate|eat|eaten|meal|food|lunch|dinner|breakfast|snack)\b", t):
            args["mentioned_meal_minutes_ago"] = mins
            mg = re.search(r"(\d+)\s*g\b", t)
            if mg:
                args["mentioned_carbs_g"] = float(mg.group(1))
        focus = next((f for f, rx in FOCUS if re.search(rx, t) and f in ("insulin", "carbs")), None)
        return "explain_now", args, focus, None
    if PAST.search(t) and not re.search(r"\bwhy\b|\?$", t) and not re.search(r"^(what|when|how|did i)\b", t):
        return "log_event", {"text": _clean_log_text(t), "minutes_ago": _minutes_ago(t)}, None, None
    if HISTORY.search(t) and not PERMISSION.search(t):
        a, b, metric = _history_window(t, now)
        return "query_history", {"start": a.isoformat(timespec="minutes"), "end": b.isoformat(timespec="minutes"), "metric": metric}, None, None
    if FORECAST.search(t) and not PERMISSION.search(t) and not re.search(r"\b(at|for)\s+\d{1,2}\b", t):
        return "get_forecast", {"hours": _forecast_hours(t, now)}, None, None
    if PERMISSION.search(t) or re.search(r"\b(tomorrow|tonight|at \d{1,2}|for \d+ min|in the morning|this evening)\b", t):
        return "evaluate_action", {"text": text}, None, None
    if NOW.search(t):
        focus = next((f for f, rx in FOCUS if re.search(rx, t)), None)
        return "get_current_state", {}, focus, None
    return "evaluate_action", {"text": text}, None, None


# ------------------------------------------------------------------ cards

CARD_OF = {"evaluate_action": "permission", "log_event": "logged", "explain_now": "explain", "whatif": "forecast", "get_forecast": "forecast",
           "query_history": "history", "get_current_state": "state", "plan_day": "plan", "change_lifestyle": "change", "compare_to_average": "text"}
CARD_PRIORITY = ["evaluate_action", "log_event", "explain_now", "whatif", "get_forecast", "query_history", "plan_day", "change_lifestyle", "get_current_state", "compare_to_average"]


def _card(results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]]) -> Dict[str, Any]:
    for name in CARD_PRIORITY:
        for n, args, res in results:
            if n == name and not res.get("error"):
                payload = dict(res)
                if name == "whatif":
                    payload["kind"] = "whatif"
                return {"type": CARD_OF[name], "payload": payload}
    return {"type": "text", "payload": {}}


# ------------------------------------------------------------------ the two routers

def _run_tool(twin, name: str, args: Dict[str, Any], text: str) -> Dict[str, Any]:
    args = dict(args or {})
    mins = args.pop("minutes_ago", None)
    try:
        res = T.call(twin, name, args)
    except Exception as ex:   # a tool failure is an answer, not a crash
        log.warning("CHAT tool %s failed: %s", name, ex)
        return {"error": f"{name} could not run ({type(ex).__name__}: {ex})"}
    if name == "log_event" and mins and res.get("event"):
        # "20 minutes ago": re-log at the stated time (the parser cannot express it)
        ev = res["event"]
        twin.logged_events.pop()
        twin.pt.events = [e for e in twin.pt.events if not (e.source == "chat" and e.start_time == ev["start_time"] and e.label == ev["label"])]
        twin.invalidate()
        ev = dict(ev)
        ev["start_time"] = (twin.now - timedelta(minutes=float(mins))).isoformat(timespec="minutes")
        res = T.call(twin, "log_event", {"event": ev})
    return res


def _local(twin, text: str) -> Dict[str, Any]:
    name, args, focus, direct = classify_local(text, twin)
    if name is None:
        return {"answer": direct, "tools": [], "results": [], "card": {"type": "text", "payload": {}}, "router": "local", "focus": focus}
    res = _run_tool(twin, name, args, text)
    answer = phrase.for_tool(name, res, text, focus)
    return {"answer": answer, "tools": [name], "results": [(name, args, res)], "card": _card([(name, args, res)]), "router": "local", "focus": focus}


def _gemini(twin, text: str) -> Dict[str, Any]:
    from google.genai import types
    from backend.adapters.gemini_common import client
    now = twin.now
    decls = [types.FunctionDeclaration(name=n, description=T.describe(n), parameters=spec["parameters"]) for n, spec in T.TOOLS.items()]
    sys_text = SYSTEM.format(date=f"{now.strftime('%A')} {fmt_date(now.isoformat())}", now=fmt12(now.isoformat(timespec='minutes')),
                             today=now.date().isoformat(), yesterday=(now - timedelta(days=1)).date().isoformat())
    sys_text += f"\nISO now: {now.isoformat(timespec='minutes')}."
    config = types.GenerateContentConfig(system_instruction=sys_text, tools=[types.Tool(function_declarations=decls)], temperature=0.1,
                                         automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                                         http_options=types.HttpOptions(timeout=40000))
    contents = [types.Content(role=h["role"], parts=[types.Part.from_text(text=h["text"])]) for h in twin.chat_history[-2 * HISTORY_TURNS:]]
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
    results: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    final = ""
    for _ in range(MAX_ROUNDS + 1):
        resp = client().models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
        calls = list(resp.function_calls or [])
        if not calls or len(results) >= MAX_ROUNDS * 3:
            final = (resp.text or "").strip()
            break
        contents.append(resp.candidates[0].content)
        parts = []
        for fc in calls:
            args = dict(fc.args or {})
            if fc.name not in T.TOOLS:
                res = {"error": f"unknown tool {fc.name}"}
            else:
                res = _run_tool(twin, fc.name, args, text)
            results.append((fc.name, args, res))
            parts.append(types.Part.from_function_response(name=fc.name, response={"result": _compact(res)}))
        contents.append(types.Content(role="user", parts=parts))
    if not final and results:
        final = " ".join(phrase.for_tool(n, r, text) for n, _, r in results if n in phrase.PHRASERS)
    return {"answer": final, "tools": [n for n, _, _ in results], "results": results, "card": _card(results), "router": "gemini"}


def handle(twin, text: str, use_gemini: Optional[bool] = None) -> Dict[str, Any]:
    """One chat turn: route, run tools, phrase, ground-check; returns what the frontend renders."""
    text = text.strip()
    use = gemini_available() if use_gemini is None else use_gemini
    out: Optional[Dict[str, Any]] = None
    if use:
        try:
            out = _gemini(twin, text)
        except Exception as ex:
            log.warning("CHAT gemini router failed (%s); using the local router", type(ex).__name__)
            out = None
    if out is None:
        out = _local(twin, text)
    results = out["results"]
    # a general-knowledge answer (no tool used, marked as general) carries textbook numbers that no tool can vouch for
    general = not results and bool(out["answer"]) and "general" in out["answer"].lower()
    violations = check_grounding(out["answer"], results, text) if (out["answer"] and not general) else []
    replaced = False
    if violations:
        log.warning("CHAT GROUNDING violation: %s not in tool results; answer replaced. text=%r answer=%r", violations, text, out["answer"])
        seen, pieces = set(), []
        for n, _, r in results:
            if n in phrase.PHRASERS and n not in seen:
                seen.add(n)
                pieces.append(phrase.for_tool(n, r, text, out.get("focus")))
        out["answer"] = " ".join(pieces) if pieces else "I could not ground that answer in your data; try asking more specifically."
        replaced = True
    if not results and out["router"] == "gemini" and not out["answer"]:
        out["answer"] = "I could not find a tool for that. Ask about your glucose now, a forecast, why it is moving, your history, or propose something."
    understood = None
    for n, _, r in results:
        if n in ("evaluate_action", "log_event") and not r.get("error"):
            understood = r.get("understood") or (r.get("plain") or {}).get("understood")
            break
    twin.chat_history.append({"role": "user", "text": text})
    twin.chat_history.append({"role": "model", "text": out["answer"]})
    twin.chat_history = twin.chat_history[-2 * HISTORY_TURNS:]
    log.info("CHAT route text=%r router=%s tools=%s grounding=%s answer=%r", text, out["router"], out["tools"], "replaced" if replaced else "ok", out["answer"][:300])
    return {"answer": out["answer"], "tools": out["tools"], "card": out["card"], "router": out["router"], "understood": understood,
            "grounding": {"ok": not violations, "violations": violations, "replaced": replaced, "general": general},
            "tool_calls": [{"name": n, "args": _compact(a)} for n, a, _ in results]}
