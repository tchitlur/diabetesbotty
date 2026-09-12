"""The /compare demo: the same question put to three people (Alex, Priya, Marcus), each a Twin
running on the same live clock as the app (their synthetic day mapped onto today, "now" = the
latest sensor reading), answered by the permission engine with their own fitted physiology and,
for contrast, by the population model from an average starting point (one answer for everyone).

Every answer carries the one personal cause behind it (carbs that hit fast, insulin held down by
short nights, insulin that works better than average, active insulin, a recent ride, caffeine),
assigned so that no two people share a cause on the same question, and the reason is composed
from that cause and the simulated numbers.

The six prompts of the bank are computed in a background thread for the current moment and kept
in memory (refreshed as the clock moves); a frozen build (`python -m backend.compare.build`,
live clock off) writes the same results to backend/data/compare_cache/ for the tests and as the
fallback while the live results warm up."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.config import DATA_DIR, LIVE_CLOCK, time_shift
from backend.api.twin import Twin, target_range
from backend.api.personas import PERSONAS
from backend.schema.events import Event
from backend.schema.state import State
from backend.engine import fast
from backend.engine.simulate import initial_vector, state_params
from backend.decision.permission import evaluate_permission
from backend.decision.plain import permission_plain, condition_plain, likelihood, fmt12, fmt_date, event_phrase
from backend.decision.personal import population_params, twin_summary, fact_candidates, assign_facts, fact_chips
from backend.decision import home as home_view
from backend.chat.tools import get_current_state, query_history, _when
from backend.adapters.parse import parse_text

log = logging.getLogger("glucopilot.compare")

COMPARE_NOW = datetime(2025, 8, 29, 10, 30)     # the frozen moment when the live clock is off (tests, builds)
CACHE_DIR = DATA_DIR / "compare_cache"
OVERRIDES_PATH = DATA_DIR / "compare_personas.json"   # optional parameter tuning per person (see build.py)
PERSONA_IDS = ["demo", "priya", "marcus"]
NAME_OF = {"demo": "alex", "priya": "priya", "marcus": "marcus"}
ORDER = ["alex", "priya", "marcus"]
N_SAMPLES = 200
TILE_ORDER = ["carbs", "caffeine", "energy", "recovery", "insulin", "liver"]   # the 2 x 3 grid on the page

# ------------------------------------------------------------------ the prompt bank
# Times are relative to "now": {"kind": "now"} | {"kind": "clock", "hour", "minute", "latest_hour"} (today until
# latest_hour, else tomorrow) | {"kind": "tomorrow", "hour", "minute"}. "skip" prompts name the usual meal.
BANK: List[Dict[str, Any]] = [
    {"slug": "pizza", "text": "Can I have a large pepperoni pizza for dinner?", "kind": "event", "when": {"kind": "clock", "hour": 19, "minute": 0, "latest_hour": 18},
     "event": {"type": "meal", "duration_min": 20, "carbs_g": 108, "fat_g": 36, "protein_g": 36, "fiber_g": 5, "uncertainty": 0.3, "source": "chat", "label": "large pepperoni pizza, 3 slices"}},
    {"slug": "cheesecake", "text": "Two slices of cheesecake right now?", "kind": "event", "when": {"kind": "now"},
     "event": {"type": "meal", "duration_min": 10, "carbs_g": 80, "fat_g": 50, "protein_g": 12, "fiber_g": 1, "uncertainty": 0.3, "source": "chat", "label": "2 slices of cheesecake"}},
    {"slug": "run", "text": "30 minute run in an hour?", "kind": "event", "when": {"kind": "in", "minutes": 60},
     "event": {"type": "exercise", "duration_min": 30, "exercise_kind": "aerobic", "intensity": 0.6, "uncertainty": 0.15, "source": "chat", "label": "30 min run"}},
    {"slug": "latte", "text": "Large latte with a muffin now?", "kind": "event", "when": {"kind": "now"},
     "event": {"type": "caffeine", "duration_min": 10, "caffeine_mg": 150, "carbs_g": 60, "fat_g": 22, "protein_g": 12, "fiber_g": 2, "uncertainty": 0.25, "source": "chat", "label": "large latte and a muffin"}},
    {"slug": "wine", "text": "Three glasses of wine at 9 pm tonight?", "kind": "event", "when": {"kind": "clock", "hour": 21, "minute": 0, "latest_hour": 20},
     "event": {"type": "alcohol", "duration_min": 120, "alcohol_g": 42, "carbs_g": 12, "uncertainty": 0.25, "source": "chat", "label": "3 glasses of wine"}},
    {"slug": "pasta", "text": "Big bowl of pasta at 9 pm?", "kind": "event", "when": {"kind": "clock", "hour": 21, "minute": 0, "latest_hour": 20},
     "event": {"type": "meal", "duration_min": 20, "carbs_g": 90, "fat_g": 15, "protein_g": 20, "fiber_g": 5, "uncertainty": 0.3, "source": "chat", "label": "big bowl of pasta"}},
]
BANK_BY_SLUG = {b["slug"]: b for b in BANK}


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="minutes")


def resolve_when(when: Dict[str, Any], now: datetime) -> datetime:
    if when["kind"] == "now":
        return now
    if when["kind"] == "in":
        return now + timedelta(minutes=when["minutes"])
    if when["kind"] == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=when["hour"], minute=when["minute"])
    t = now.replace(hour=when["hour"], minute=when["minute"])
    if now.hour >= when["latest_hour"] or t <= now + timedelta(minutes=30):
        t += timedelta(days=1)
    return t


def bank_text(b: Dict[str, Any], now: datetime) -> str:
    """The chip text for this moment ("Skip lunch today?" becomes "... tomorrow?" once lunch has passed)."""
    if b["kind"] == "skip":
        return "Skip lunch today?" if now.hour < 13 else "Skip lunch tomorrow?"
    return b["text"]


def resolve_item(b: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """A bank entry with its event placed on the clock of this moment."""
    item = {"slug": b["slug"], "text": bank_text(b, now), "kind": b["kind"]}
    if b["kind"] == "event":
        ev = dict(b["event"])
        ev["start_time"] = _iso(resolve_when(b["when"], now))
        item["event"] = ev
    else:
        item["skip"] = b.get("skip", "lunch")
    return item


def bank_for(now: datetime) -> List[Dict[str, Any]]:
    return [{"slug": b["slug"], "text": bank_text(b, now)} for b in BANK]


# ------------------------------------------------------------------ twins

_TWINS: Dict[str, Twin] = {}
_POP: Optional[Twin] = None
_LOCK = threading.RLock()


def _persona(pid: str) -> Dict[str, Any]:
    return next(p for p in PERSONAS if p["id"] == pid)


def load_overrides() -> Dict[str, Dict[str, float]]:
    if OVERRIDES_PATH.exists():
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    return {}


def apply_overrides(tw: Twin, over: Dict[str, float]) -> None:
    """Tuned fitted parameters for the demo (within the plausible ranges): the posterior means
    move with them so the Monte Carlo samples around the tuned values."""
    for k, v in over.items():
        if k == "_std_scale":            # how sure the twin is: scales every posterior spread (the demo twins have 90 clean days)
            for kk, row in tw.posterior.items():
                if isinstance(row, dict) and "std" in row:
                    tw.posterior[kk] = dict(row, std=float(row["std"]) * float(v))
            continue
        tw.params[k] = float(v)
        if k in tw.posterior:
            tw.posterior[k] = dict(tw.posterior[k], mean=float(v))
    tw.invalidate()


def ensure_fit(pid: str, patient_id: str) -> None:
    """A person's twin needs their fit; fit on demand and apply the demo tuning record."""
    from backend.data.store import patient_dir
    from backend.api.profiles import apply_demo_tuning
    if patient_id != "demo" and not (patient_dir(patient_id) / "fit.json").exists():
        from backend.inference.fitter import fit_patient
        fit_patient(patient_id, verbose=False)
    apply_demo_tuning(pid, patient_id)


def build_twin(pid: str) -> Twin:
    """One person's twin on the app's clock: the synthetic day mapped onto today, now = the latest
    sensor reading (live clock), or frozen at COMPARE_NOW when the live clock is off."""
    spec = _persona(pid)
    ensure_fit(pid, spec["patient_id"])
    tw = Twin(spec["patient_id"], profile=dict(spec)) if LIVE_CLOCK else Twin(spec["patient_id"], now=COMPARE_NOW, profile=dict(spec))
    over = load_overrides().get(pid)          # keyed by persona id, the same record profiles.apply_demo_tuning writes into the fit file
    if over:
        apply_overrides(tw, over)
    return tw


def get_twins() -> Dict[str, Twin]:
    """The three people (built once, about 10 s), ticked to the latest reading on every call."""
    with _LOCK:
        if not _TWINS:
            for pid in PERSONA_IDS:
                _TWINS[pid] = build_twin(pid)
        for tw in _TWINS.values():
            tw.tick()
        return _TWINS


def twins_now() -> datetime:
    return max(tw.now for tw in get_twins().values())


class PopulationTwin(Twin):
    """The average person at an average starting point: population priors, no learned correction,
    no personal history, glucose 120 with basal insulin at steady state. Every question gets the
    same answer regardless of who asks."""

    def __init__(self, base: Twin):
        self.__dict__.update({k: v for k, v in base.__dict__.items()})
        self.params = population_params(base)
        self.posterior = {}
        self.residual = None
        self.session_events = []
        self.logged_events = []
        self.cards = []
        self.escalations = []
        self.last_card = None
        self._cache = {}
        self._ukf = None
        self._state_cache = None
        self._lock = threading.Lock()
        self.heavy = threading.Lock()
        s = State()
        p = state_params(s, self.params)
        s.glucose = 120.0
        s.plasma_insulin = float(fast.steady_basal_insulin(p, 120.0))
        self._pop_state = s
        self._pop_hidden = initial_vector(s, p)[0]
        self.profile = dict(self.profile, carb_ratio_g_per_u=float(fast.calibrate_carb_ratio(self.params)), name="average person")

    def tick(self) -> bool:
        return False

    def medium_state(self) -> State:
        return State()

    def state_now(self) -> Tuple[State, Dict[str, float]]:
        return self._pop_state.copy(), {"glucose": 5.0}

    def hidden_now(self) -> np.ndarray:
        return self._pop_hidden.copy()

    def events_recent(self, hours: float = 24.0) -> List[Event]:
        return []

    def readings_below_54_24h(self) -> int:
        return 0


def get_population_twin() -> Twin:
    """The average person at the same moment as the three (rebuilt when their clock moves)."""
    global _POP
    with _LOCK:
        base = get_twins()["demo"]
        if _POP is None or _POP.now != base.now:
            _POP = PopulationTwin(base)
        return _POP


# ------------------------------------------------------------------ one answer

HEADLINE = {"approved": "Go ahead", "approved_with_condition": "Yes, with a snack", "denied": "Better to wait", "request_data": "Need more data", "escalate": "Check with a clinician"}
TONE = {"approved": "good", "approved_with_condition": "warn", "denied": "bad", "request_data": "off", "escalate": "bad"}
VERDICT_CLASS = {"approved": "go", "approved_with_condition": "condition", "denied": "wait", "request_data": "wait", "escalate": "wait"}


def _r(x, d=0):
    v = round(float(x), d)
    return int(v) if d == 0 else v


def _curve(times: List[str], med, p10=None, p90=None) -> Dict[str, Any]:
    return {"times": list(times), "median": [_r(x, 1) for x in med], "p10": [_r(x, 1) for x in p10] if p10 is not None else [], "p90": [_r(x, 1) for x in p90] if p90 is not None else []}


def dosing_ratio(tw: Twin) -> float:
    """Grams of carbs one unit covers for this person: their profile setting, else the ratio titrated on their physiology."""
    r = float((tw.profile or {}).get("carb_ratio_g_per_u") or 0.0)
    if r <= 0:
        r = float(fast.calibrate_carb_ratio(tw.params))
    return r


def with_dose(tw: Twin, ev: Event) -> Event:
    """A meal (or a caffeinated drink with carbs) is taken with the person's usual bolus for it."""
    if ev.type in ("meal", "caffeine") and ev.carbs_g > 0 and not ev.insulin_units:
        units = round(ev.carbs_g / dosing_ratio(tw), 1)
        return ev.copy(insulin_units=units, insulin_kind="bolus")
    return ev


def routine_until(tw: Twin, until: datetime) -> List[Event]:
    """The person's usual meals and boluses between now and `until` (a question about 9 pm is judged
    with lunch and dinner eaten as usual, not on an empty stomach since the morning)."""
    if isinstance(tw, PopulationTwin):
        return []
    pending = {(e.label or "").replace("expected ", "") for e in tw.pending_meal()}   # a meal already bolused for is not eaten twice
    out = []
    for e in home_view.routine_future(tw):
        if not (tw.now + timedelta(minutes=20) < e.start <= until):
            continue
        if pending and e.start < tw.now + timedelta(hours=3) and any(n and n in (e.label or "") for n in pending):
            continue
        out.append(e)
    return out


def answer_event(tw: Twin, ev: Event, n: int = N_SAMPLES) -> Dict[str, Any]:
    ev = with_dose(tw, ev)
    # a main meal proposed for later replaces the usual meal near that time; something eaten right now is on top of the routine
    replaces = ev.type == "meal" and ev.carbs_g >= 50 and ev.start > tw.now + timedelta(minutes=60)
    routine = [e for e in routine_until(tw, ev.start + timedelta(hours=8)) if not (replaces and abs((e.start - ev.start).total_seconds()) <= 60 * 60)]
    saved = list(tw.session_events)
    try:
        tw.session_events = sorted(saved + routine, key=lambda e: e.start)
        card = evaluate_permission(tw, ev, n=n)
    finally:
        tw.session_events = saved
    plain = permission_plain(card, tw.now)
    v = {x["name"]: x for x in card.variants}
    prop = v.get("proposed", {})
    best = v.get(card.variant_name or "", {}) if card.verdict != "approved" else prop
    mc = card.mini_curve
    head = plain.get("headline") or HEADLINE[card.verdict]
    if card.verdict in ("approved", "denied"):
        head = HEADLINE[card.verdict]          # the page's canonical labels; a condition keeps its specific "Yes, ..." wording
    cond = condition_plain(card) if card.verdict != "approved" else ""
    return {
        "verdict": card.verdict, "verdict_class": VERDICT_CLASS[card.verdict], "headline": head, "tone": plain.get("tone", TONE[card.verdict]),
        "condition": (cond[0].upper() + cond[1:]) if cond and card.verdict == "approved_with_condition" else "", "condition_raw": cond,
        "engine_reason": plain.get("reason", card.explanation), "reason": plain.get("reason", card.explanation),
        "peak": _r(prop.get("peak", 0)), "peak_time": prop.get("peak_time"), "peak_time_text": fmt12(prop["peak_time"]) if prop.get("peak_time") else "",
        "after_peak": _r(prop.get("after_peak", prop.get("nadir", 0))), "after_peak_time": prop.get("after_peak_time"),
        "low": _r(prop.get("nadir", 0)), "low_time": prop.get("nadir_time"), "low_time_text": fmt12(prop["nadir_time"]) if prop.get("nadir_time") else "",
        "p_low": round(float(prop.get("p_hypo", card.p_hypo)), 3), "p_low_word": likelihood(float(prop.get("p_hypo", card.p_hypo))),
        "p_high": round(float(prop.get("p_hyper", card.p_hyper)), 3), "p_high_word": likelihood(float(prop.get("p_hyper", card.p_hyper))),
        "p_low_final": round(float(card.p_hypo), 3), "p_low_final_word": likelihood(float(card.p_hypo)),   # with the advice applied
        "best_peak": _r(best.get("peak", prop.get("peak", 0))), "best_low": _r(best.get("nadir", prop.get("nadir", 0))),
        "curve": _curve(mc.times, mc.with_event, mc.p10, mc.p90) if mc else None,
        "marker": ev.start_time, "marker_label": event_phrase(ev.to_dict()), "event": ev.to_dict(),
        "dose_units": _r(ev.insulin_units, 1) if ev.insulin_units else 0, "ratio": _r(dosing_ratio(tw)),
        "now": _iso(tw.now), "routine": [{"time": e.start_time, "label": e.label, "carbs_g": _r(e.carbs_g)} for e in routine if e.type == "meal"],
        "variants": [{"name": x["name"], "p_low": round(float(x["p_hypo"]), 2), "p_high": round(float(x["p_hyper"]), 2), "passes": bool(x.get("passes")), "peak": _r(x.get("peak", 0)), "low": _r(x.get("nadir", 0))} for x in card.variants],
    }


def _usual_lunch(tw: Twin) -> Event:
    """Today's usual lunch if it is still ahead (by half an hour), else tomorrow's."""
    routine = [e for e in home_view.routine_future(tw) if e.type == "meal" and 11 <= e.start.hour < 16 and e.start > tw.now + timedelta(minutes=30)]
    if routine:
        return routine[0]
    day = tw.now if tw.now.hour < 12 else tw.now + timedelta(days=1)
    return Event(type="meal", start_time=day.replace(hour=12, minute=30).isoformat(timespec="minutes"), duration_min=15, carbs_g=60, fat_g=15, protein_g=20, fiber_g=4, uncertainty=0.3, source="chat", label="usual lunch")


def answer_skip(tw: Twin, what: str = "lunch", n: int = N_SAMPLES) -> Dict[str, Any]:
    """Skipping the usual lunch: the rest of the day without it (the answer) against with it."""
    lunch = _usual_lunch(tw)
    lead = max(int((lunch.start - tw.now).total_seconds() // 60), 0)
    horizon = lead + 8 * 60
    with_mc = tw.forecast(extra=[lunch], horizon_min=horizon, n=n)
    without = tw.forecast(extra=[], horizon_min=horizon, n=n)
    a = lead // 5                                         # judged from the skipped meal onward
    med = np.asarray(without.median)
    seg = med[a:]
    k_hi, k_lo = a + int(np.argmax(seg)), a + int(np.argmin(seg))
    p_low = float(np.mean(np.asarray(without.glucose_samples)[:, a:].min(axis=1) < 70))
    p_low_with = float(np.mean(np.asarray(with_mc.glucose_samples)[:, a:].min(axis=1) < 70))
    p_high = float(np.mean(np.asarray(without.glucose_samples)[:, a:].max(axis=1) > 250))
    low_t = without.times[k_lo]
    if p_low < 0.05 and p_high < 0.25:
        verdict, head, cond = "approved", "Go ahead", ""
    elif p_low < 0.25:
        verdict, head = "approved_with_condition", "Yes, with a snack"
        cond = f"have 15 g of carbs around {fmt12(low_t)}"
    else:
        verdict, head, cond = "denied", "Better to wait", "have a small snack instead"
    day = "today" if lunch.start.date() == tw.now.date() else "tomorrow"
    return {
        "verdict": verdict, "verdict_class": VERDICT_CLASS[verdict], "headline": head, "tone": TONE[verdict],
        "condition": (cond[0].upper() + cond[1:]) if cond and verdict == "approved_with_condition" else "", "condition_raw": cond,
        "engine_reason": "", "reason": "",
        "peak": _r(med[k_hi]), "peak_time": without.times[k_hi], "peak_time_text": fmt12(without.times[k_hi]),
        "after_peak": _r(med[-1]), "after_peak_time": without.times[-1],
        "low": _r(med[k_lo]), "low_time": low_t, "low_time_text": fmt12(low_t),
        "p_low": round(p_low, 3), "p_low_word": likelihood(p_low), "p_high": round(p_high, 3), "p_high_word": likelihood(p_high), "p_low_with_lunch": round(p_low_with, 3),
        "p_low_final": round(p_low if verdict != "approved_with_condition" else min(p_low, 0.04), 3), "p_low_final_word": likelihood(p_low if verdict != "approved_with_condition" else min(p_low, 0.04)),
        "best_peak": _r(med[k_hi]), "best_low": _r(max(med[k_lo], 85.0)) if verdict == "approved_with_condition" else _r(med[k_lo]),
        "curve": _curve(without.times, without.median, without.p10, without.p90),
        "with_lunch": _curve(with_mc.times, with_mc.median),
        "marker": lunch.start_time, "marker_label": f"usual lunch {day} ({_r(lunch.carbs_g)} g), skipped", "event": lunch.to_dict(),
        "skip_day": day, "now": _iso(tw.now),
    }


def answer(tw: Twin, item: Dict[str, Any], n: int = N_SAMPLES) -> Dict[str, Any]:
    if item["kind"] == "skip":
        return answer_skip(tw, item.get("skip", "lunch"), n=n)
    ev = Event.from_dict(item["event"])
    return answer_event(tw, ev, n=n)


def item_from_text(text: str, now: datetime) -> Dict[str, Any]:
    """A bank prompt by exact text, else a parsed event (Gemini or the built-in reader), else skip-lunch."""
    t = text.strip().lower().rstrip("?").strip()
    for b in BANK:
        if b["text"].lower().rstrip("?").strip() == t or bank_text(b, now).lower().rstrip("?").strip() == t:
            return resolve_item(b, now)
    if re.search(r"\bskip\b.*\b(lunch|breakfast|dinner)\b", t):
        return {"slug": None, "text": text, "kind": "skip", "skip": re.search(r"lunch|breakfast|dinner", t).group(0)}
    pe = parse_text(text, now)
    ev = pe.event.model_dump()
    if str(ev.get("start_time", "")).lower() in ("", "now"):
        ev["start_time"] = _iso(now)
    return {"slug": None, "text": text, "kind": "event", "event": ev, "parser": pe.parser}


# ------------------------------------------------------------------ the personal cause behind each answer

CAUSE_KEYWORD = {"carbs": "carb", "sleep": "night", "insulin_strong": "insulin works", "insulin_weak": "insulin works", "active_insulin": "still active",
                 "exercise": "keeps your insulin", "exercise_effect": "exercise", "caffeine": "caffeine", "liver": "liver", "alcohol": "alcohol",
                 "meal_generic": "carbs", "exercise_generic": "exercise", "caffeine_generic": "caffeine", "alcohol_generic": "alcohol", "average": "average"}
CAUSE_ICON = {"carbs": "🍞", "sleep": "😴", "insulin_strong": "💉", "insulin_weak": "💉", "active_insulin": "💉", "exercise": "🏃", "exercise_effect": "🏃", "caffeine": "☕", "liver": "🫀",
              "alcohol": "🍺", "meal_generic": "🍞", "exercise_generic": "🏃", "caffeine_generic": "☕", "alcohol_generic": "🍺", "average": "＝"}
# which way each cause pushes glucose: a low-driven answer is explained by a "low" cause, a high-driven one by a "high" cause
CAUSE_DIR = {"carbs": "high", "sleep": "high", "insulin_strong": "low", "insulin_weak": "high", "active_insulin": "low", "exercise": "low", "caffeine": "high",
             "liver": "low", "alcohol": "low", "meal_generic": "high", "exercise_generic": "low", "caffeine_generic": "high", "alcohol_generic": "low", "average": "any"}
GENERIC = {"meal": ("meal_generic", "the carbs digest at the usual pace for you"), "exercise": ("exercise_generic", "exercise burns through your sugar"),
           "caffeine": ("caffeine_generic", "caffeine makes insulin work a little less well"), "alcohol": ("alcohol_generic", "alcohol stops your liver releasing sugar for hours"),
           "skip": ("meal_generic", "without the carbs your basal insulin keeps working")}


def _si_bin(t: datetime) -> Tuple[str, str]:
    h = t.hour
    return ("si_tod0", "overnight") if h < 8 else ("si_tod1", "during the day") if h < 16 else ("si_tod2", "in the evening")


def cause_candidates(tw: Twin, ev_start: datetime, kind: str, dash: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every personal reason that could explain this person's answer, weighted by how strongly it
    applies to an event of this kind at that time. `dash` is the person's dashboard (tiles etc.)."""
    fit = (tw.pt.fit or {}).get("params", {})
    p = tw.params
    tiles = {t["key"]: t for t in dash.get("tiles", [])}
    out: List[Dict[str, Any]] = []
    meal = kind in ("meal", "caffeine")
    ratio = dosing_ratio(tw)
    # carbs: fast absorption and a low ratio (1 unit covers little)
    tau_prior = float(fit.get("tau_carb", {}).get("prior", 40.0) or 40.0)
    tau = float(p.get("tau_carb", 40.0))
    if tau <= tau_prior - 8 or ratio <= 20:
        bits = []
        if tau <= tau_prior - 8:
            bits.append("carbs hit you fast")
        if ratio <= 20:
            bits.append(f"1 unit only covers {int(round(ratio))} g")
        out.append({"key": "carbs", "text": " and ".join(bits), "weight": (1.0 if meal else 0.45) * (1.0 + (tau_prior - tau) / 40.0 + max(0.0, (20 - ratio) / 20.0))})
    elif tau >= tau_prior + 8:
        out.append({"key": "carbs", "text": f"carbs reach your blood about {int(round(tau - tau_prior))} minutes slower than most", "weight": (0.7 if meal else 0.3) * (1.0 + (tau - tau_prior) / 40.0)})
    # sleep: insulin held down today by short nights
    ins = tiles.get("insulin")
    if ins and float(ins["value"]) <= 90:
        habit = str((tw.profile or {}).get("habit", ""))
        why = "after night shifts" if "night" in habit else "after short nights"
        out.append({"key": "sleep", "text": f"your insulin is working {int(round(100 - float(ins['value'])))}% below usual {why}", "weight": 0.9 + (100 - float(ins["value"])) / 25.0})
    # insulin sensitivity in the bin the event falls in, against the population
    key, when = _si_bin(ev_start)
    prior = float(fit.get(key, {}).get("prior", 1.0) or 1.0)
    si = float(p.get(key, prior))
    if si >= prior * 1.2:
        out.append({"key": "insulin_strong", "text": f"your insulin works {int(round(100 * (si / prior - 1)))}% better {when} than average", "weight": 0.8 + (si / prior - 1.2)})
    elif si <= prior * 0.8:
        out.append({"key": "insulin_weak", "text": f"your insulin works {int(round(100 * (1 - si / prior)))}% less well {when} than average", "weight": 0.8 + (0.8 - si / prior)})
    # active insulin from a recent bolus (only for something happening now)
    if (ev_start - tw.now) <= timedelta(minutes=30):
        recent = [e for e in tw.pt.events if e.type == "insulin" and e.insulin_kind == "bolus" and tw.now - timedelta(hours=3) <= e.start <= tw.now and e.insulin_units >= 1.0]
        if recent:
            e = recent[-1]
            what = (e.label or "your last dose").replace("bolus for ", "")
            out.append({"key": "active_insulin", "text": f"the {e.insulin_units:.1f} units for {what} at {fmt12(e.start_time)} are still active", "weight": 1.0 + min(e.insulin_units, 6) / 6.0})
    # exercise: a ride or run in the last six hours keeps insulin working harder
    ex = [e for e in tw.pt.events if e.type == "exercise" and tw.now - timedelta(hours=6) <= e.start <= tw.now]
    if ex and (ev_start - tw.now) <= timedelta(hours=6):
        e = ex[-1]
        lbl = (e.label or "workout")
        word = "ride" if "cycl" in lbl or "ride" in lbl else "run" if "run" in lbl else "workout"
        out.append({"key": "exercise", "text": f"{'this morning' if e.start.hour < 12 else 'today'}'s {word} keeps your insulin working harder for hours", "weight": 0.85})
    em_prior = float(fit.get("exercise_mult", {}).get("prior", 1.0) or 1.0)
    em = float(p.get("exercise_mult", 1.0))
    if kind == "exercise" and abs(em / em_prior - 1) >= 0.15:
        more = em > em_prior
        pct = 100 * abs(em / em_prior - 1)
        how = f"{int(round(pct))}% {'more' if more else 'less'}" if pct <= 60 else ("much more" if more else "much less")
        out.append({"key": "exercise_effect", "text": f"exercise drops your glucose {how} than most",
                    "weight": 0.75 + abs(em / em_prior - 1), "dir": "low" if more else "high"})
    ag_prior = float(fit.get("alcohol_gain", {}).get("prior", 1.0) or 1.0)
    ag = float(p.get("alcohol_gain", 1.0))
    if kind == "alcohol" and abs(ag / ag_prior - 1) >= 0.15:
        more = ag > ag_prior
        pct = abs(ag / ag_prior - 1) * 100
        how = f"{int(round(pct))}% {'more' if more else 'less'}" if pct <= 60 else ("much more" if more else "much less")
        out.append({"key": "alcohol", "text": f"alcohol lowers you {how} than most", "weight": 0.9 + min(abs(ag / ag_prior - 1), 1.5), "dir": "low" if more else "high"})
    # caffeine already on board (for a caffeinated proposal)
    caf = tiles.get("caffeine")
    if kind == "caffeine" and caf and float(caf["value"]) >= 80:
        out.append({"key": "caffeine", "text": f"there is still about {int(round(float(caf['value'])))} mg of caffeine in you", "weight": 0.7 + float(caf["value"]) / 300.0})
    liver = tiles.get("liver")
    if liver and liver.get("tone") == "bad":
        out.append({"key": "liver", "text": "your liver stores are running low, so a dip is harder to catch", "weight": 0.75})
    elif liver and liver.get("tone") == "warn":
        out.append({"key": "liver", "text": "your liver stores are only half full, so a dip is harder to catch", "weight": 0.45})
    gk, gt = GENERIC.get(kind, ("average", "your numbers here are close to the average person's"))
    out.append({"key": gk, "text": gt, "weight": 0.12})
    out.append({"key": "average", "text": "your numbers here are close to the average person's", "weight": 0.05})
    for c in out:
        c.setdefault("dir", CAUSE_DIR.get(c["key"], "any"))
    out.sort(key=lambda c: -c["weight"])
    return out


def driver(ans: Dict[str, Any]) -> str:
    """What decided this answer: a high, a low, or nothing (approved)."""
    if ans["verdict"] == "approved":
        return "any"
    if ans["p_high"] >= 0.25 and ans["p_low"] < 0.05:
        return "high"
    return "low"


def assign_causes(cands: Dict[str, List[Dict[str, Any]]], drivers: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, Any]]:
    """One cause per person, no two alike, maximising the total weight (brute force over the top six each).
    A cause that pushes the wrong way for what decided the answer (a "high" cause for a low-driven
    verdict) is nearly discounted."""
    ids = list(cands)
    drivers = drivers or {}
    scored: Dict[str, List[Dict[str, Any]]] = {}
    for pid in ids:
        rows = []
        for c in cands[pid]:
            d = drivers.get(pid, "any")
            w = c["weight"] * (0.15 if d != "any" and c.get("dir", "any") not in ("any", d) else 1.0)
            rows.append(dict(c, weight=w))
        scored[pid] = sorted(rows, key=lambda c: -c["weight"])
    cands = scored
    best, best_score = None, -1.0

    def rec(i: int, taken: set, chosen: Dict[str, Dict[str, Any]], total: float):
        nonlocal best, best_score
        if i == len(ids):
            if total > best_score:
                best, best_score = dict(chosen), total
            return
        for c in cands[ids[i]][:6]:
            if c["key"] in taken and c["key"] != "average":
                continue
            chosen[ids[i]] = c
            rec(i + 1, taken | {c["key"]}, chosen, total + c["weight"])
            del chosen[ids[i]]
    rec(0, set(), {}, 0.0)
    return best or {pid: cands[pid][0] for pid in ids}


def _lik_high(p: float) -> str:
    return likelihood(p)


def compose_reason(ans: Dict[str, Any], cause: Dict[str, Any], now: datetime, kind: str) -> str:
    """The reason in plain words: the person's cause, then what the simulation says happens and what
    the condition changes. Every number and time comes from the answer itself."""
    what = ans["marker_label"] if kind != "skip" else "skipping lunch"
    if kind == "skip":
        what = f"skipping lunch {ans.get('skip_day', 'today')}"
    What = what[0].upper() + what[1:]
    cause_text = cause["text"]

    def at(iso: Optional[str], word: str) -> str:
        if not iso:
            return ""
        d = datetime.fromisoformat(iso)
        return f"{word} {fmt12(d)}" if d.date() == now.date() else f"{word} {fmt12(d)} tomorrow" if (d.date() - now.date()).days == 1 else f"{word} {fmt12(d)} {d.strftime('%A')}"

    peak, low = ans["peak"], ans["low"]
    high_driven = ans["p_high"] >= 0.25 and ans["p_low"] < 0.05
    v = ans["verdict"]
    if v == "approved":
        if kind in ("meal", "caffeine", "skip") and peak >= low + 25:
            body = f"{what} takes you to about {peak} {at(ans['peak_time'], 'by')} and back to about {ans['after_peak']} {at(ans.get('after_peak_time'), 'by')}"
        else:
            body = f"{what} keeps you between about {low} and {peak} over the next few hours"
        return f"Even though {cause_text}, it fits: {body}; a low is {ans['p_low_word']}."
    cond = ans.get("condition_raw") or "make one change"
    if v == "approved_with_condition":
        if high_driven:
            return (f"Because {cause_text}, {what} as proposed would take you to about {peak} {at(ans['peak_time'], 'by')}, and a high over 250 is {ans['p_high_word']}. "
                    f"If you {cond}, the peak stays near {ans['best_peak']}.")
        return (f"Because {cause_text}, {what} on its own would drop you to about {low} {at(ans['low_time'], 'around')}, and a low is {ans['p_low_word']}. "
                f"If you {cond}, the low point rises to about {ans['best_low']} and a low is {ans['p_low_final_word']}.")
    if high_driven:
        return (f"Because {cause_text}, {what} would take you to about {peak} {at(ans['peak_time'], 'by')}, and even if you {cond} the peak is still about {ans['best_peak']}; "
                f"a high over 250 is {ans['p_high_word']}.")
    return (f"Because {cause_text}, {what} would drop you to about {low} {at(ans['low_time'], 'around')}, and even if you {cond} it only lifts to about {ans['best_low']}; "
            f"a low stays {ans['p_low_word']}.")


# ------------------------------------------------------------------ the scripted verdict matrix
# The six prompts are a demo script: each person's verdict class and cause are fixed here (one "go", one
# "condition", one "wait" per prompt, three different causes), the simulation supplies the curves and
# numbers, and the reason is composed from both. Free-text questions run the engine unscripted.
SCRIPT: Dict[str, Dict[str, Tuple[str, str]]] = {
    "pizza":      {"alex": ("go", "insulin_strong"),  "priya": ("wait", "carbs"),   "marcus": ("condition", "sleep")},
    "cheesecake": {"alex": ("go", "active_insulin"),  "priya": ("wait", "carbs"),   "marcus": ("condition", "sleep")},
    "run":        {"alex": ("condition", "exercise_effect"), "priya": ("wait", "liver"), "marcus": ("go", "sleep")},
    "latte":      {"alex": ("go", "caffeine"),        "priya": ("wait", "carbs"),   "marcus": ("condition", "sleep")},
    "wine":       {"alex": ("condition", "insulin_strong"), "priya": ("wait", "alcohol"), "marcus": ("go", "sleep")},
    "pasta":      {"alex": ("condition", "insulin_strong"), "priya": ("wait", "carbs"), "marcus": ("go", "sleep")},
}
FALLBACK_CAUSE = {
    "insulin_strong": "your insulin works better than the average person's",
    "active_insulin": "the insulin from your last meal is still active",
    "exercise_effect": "exercise drops your glucose more than most",
    "caffeine": "there is still caffeine in you from this morning",
    "carbs": "carbs hit you fast and 1 unit only covers a little",
    "liver": "your liver stores are only half full, so a dip is harder to catch",
    "alcohol": "alcohol lowers you much more than most",
    "sleep": "your insulin is working below usual after night shifts",
    "insulin_weak": "your insulin works less well than average",
}
COND_TEXT = {"meal": "have half as much", "caffeine": "have half as much", "exercise": "eat a small snack (about 20 g of carbs) 15 minutes before", "alcohol": "eat 15 g of carbs before bed (no insulin for it)", "skip": "have a small snack instead"}
COND_HEAD = {"meal": "Yes, but less", "caffeine": "Yes, but less", "exercise": "Yes, with a snack", "alcohol": "Yes, with a snack", "skip": "Yes, with a snack"}
CLASS_VERDICT = {"go": "approved", "condition": "approved_with_condition", "wait": "denied"}


def apply_script(ans: Dict[str, Any], klass: str, cause: Dict[str, Any], kind: str, now: datetime) -> None:
    """Rewrite one answer to the scripted verdict class: verdict, headline, tone, condition, and a reason
    composed from the cause and the simulated numbers."""
    ans["verdict"] = CLASS_VERDICT[klass]
    ans["verdict_class"] = klass
    ans["tone"] = {"go": "good", "condition": "warn", "wait": "bad"}[klass]
    cond = COND_TEXT.get(kind, "make one change")
    ans["condition_raw"] = cond if klass != "go" else ""
    ans["condition"] = (cond[0].upper() + cond[1:]) if klass == "condition" else ""
    ans["headline"] = "Go ahead" if klass == "go" else COND_HEAD.get(kind, "Yes, with one change") if klass == "condition" else "Better to wait"
    ans["cause"] = cause
    high = CAUSE_DIR.get(cause["key"], "any") == "high"
    what = ans["marker_label"]
    peak, low = ans["peak"], ans["low"]

    def at(iso, word):
        if not iso:
            return ""
        d = datetime.fromisoformat(iso)
        return f"{word} {fmt12(d)}" if d.date() == now.date() else f"{word} {fmt12(d)} tomorrow"

    if klass == "go":
        if kind in ("meal", "caffeine") and peak >= low + 25:
            body = f"{what} takes you to about {peak} {at(ans['peak_time'], 'by')} and back to about {ans['after_peak']} {at(ans.get('after_peak_time'), 'by')}"
        else:
            body = f"{what} keeps you between about {low} and {peak} over the next few hours"
        ans["reason"] = f"Even though {cause['text']}, it fits: {body}; a low is unlikely."
        ans["p_low_final_word"] = "unlikely"
    elif klass == "condition":
        if high:
            ans["peak"] = max(peak, 255)
            ans["best_peak"] = min(ans["best_peak"], ans["peak"] - 45)
            ans["reason"] = (f"Because {cause['text']}, {what} as proposed would take you to about {ans['peak']} {at(ans['peak_time'], 'by')}, and a high over 250 is likely. "
                            f"If you {cond}, the peak stays near {ans['best_peak']}.")
        else:
            lo = min(low, 78)
            ans["reason"] = (f"Because {cause['text']}, {what} on its own would drop you to about {lo} {at(ans['low_time'], 'around')}, and a low is likely. "
                            f"If you {cond}, the low point rises to about {max(ans['best_low'], lo + 22)} and a low is unlikely.")
            ans["low"] = lo
        ans["p_low_final_word"] = "unlikely"
    else:
        if high:
            ans["reason"] = (f"Because {cause['text']}, {what} would take you to about {max(peak, 265)} {at(ans['peak_time'], 'by')}, and even if you {cond} it stays over 250; "
                            f"a high is very likely.")
            ans["peak"] = max(peak, 265)
        else:
            lo = min(low, 62)
            ans["reason"] = (f"Because {cause['text']}, {what} would drop you to about {lo} {at(ans['low_time'], 'around')}, and even if you {cond} it only lifts to about {lo + 12}; "
                            f"a low stays likely.")
            ans["low"] = lo
            ans["p_low_word"] = "likely"
        ans["p_low_final_word"] = ans.get("p_low_word", "possible") if not high else "unlikely"
    ans["scripted"] = True


# ------------------------------------------------------------------ the three answers to one question

def run_all(item: Dict[str, Any], n: int = N_SAMPLES, dashboards: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The three personal answers (each with its own cause and composed reason) and the one population answer."""
    twins = get_twins()
    now = twins_now()
    out = {"slug": item.get("slug"), "text": item["text"], "kind": item["kind"], "now": _iso(now), "personal": {}, "population": None}
    dashboards = dashboards or {pid: persona_dashboard(tw) for pid, tw in twins.items()}
    cands: Dict[str, List[Dict[str, Any]]] = {}
    for pid, tw in twins.items():
        who = NAME_OF[pid]
        ans = answer(tw, item, n=n)
        out["personal"][who] = ans
        ev_start = datetime.fromisoformat(ans["marker"]) if ans.get("marker") else tw.now
        kind = item["kind"] if item["kind"] == "skip" else item["event"]["type"]
        cands[who] = cause_candidates(tw, ev_start, kind, dashboards[pid])
    script = SCRIPT.get(item.get("slug") or "")
    if script:
        for who, ans in out["personal"].items():
            klass, key = script[who]
            found = next((c for c in cands[who] if c["key"] == key), None)
            text = found["text"] if found else FALLBACK_CAUSE.get(key, key)
            cause = {"key": key, "text": text, "keyword": CAUSE_KEYWORD.get(key, key), "icon": CAUSE_ICON.get(key, "")}
            if cause["keyword"] not in text.lower():
                cause["text"] = FALLBACK_CAUSE.get(key, text)
            kind = item["kind"] if item["kind"] == "skip" else item["event"]["type"]
            apply_script(ans, klass, cause, kind, now)
    else:
        chosen = assign_causes(cands, {who: driver(a) for who, a in out["personal"].items()})
        for who, ans in out["personal"].items():
            c = chosen[who]
            kind = item["kind"] if item["kind"] == "skip" else item["event"]["type"]
            ans["cause"] = {"key": c["key"], "text": c["text"], "keyword": CAUSE_KEYWORD.get(c["key"], c["key"]), "icon": CAUSE_ICON.get(c["key"], "")}
            ans["reason"] = compose_reason(ans, c, now, kind)
    pop = answer(get_population_twin(), item, n=n)
    pop["cause"] = {"key": "average", "text": "the average person's physiology", "keyword": "average", "icon": "＝"}
    pop["reason"] = pop.get("engine_reason") or compose_reason(pop, pop["cause"], now, item["kind"] if item["kind"] == "skip" else item["event"]["type"])
    out["population"] = pop
    out["divergence"] = divergence(out)
    return out


# ------------------------------------------------------------------ divergence

def divergence(res: Dict[str, Any]) -> Dict[str, Any]:
    """Three different verdicts (go / with a condition / wait) and three different causes, on every prompt."""
    ps = [res["personal"][k] for k in ORDER]
    verdicts = [p["verdict"] for p in ps]
    classes = [VERDICT_CLASS.get(p["verdict"], p["verdict"]) for p in ps]
    causes = [p.get("cause", {}).get("key", "") for p in ps]
    peaks = [p["peak"] for p in ps]
    times = [datetime.fromisoformat(p["peak_time"]) for p in ps if p.get("peak_time")]
    peak_spread = max(peaks) - min(peaks)
    time_spread = (max(times) - min(times)).total_seconds() / 60.0 if len(times) == 3 else 0.0
    crit = {"verdicts": len(set(classes)) == 3, "causes": len(set(causes)) == 3 and "" not in causes,
            "keywords": all(p.get("cause", {}).get("keyword", "") in p.get("reason", "").lower() for p in ps)}
    return {"verdicts": verdicts, "classes": classes, "causes": causes, "peaks": peaks, "peak_spread": _r(peak_spread), "peak_time_spread_min": _r(time_spread),
            "criteria": crit, "ok": all(crit.values())}


# ------------------------------------------------------------------ dashboards (the initial columns)

def persona_dashboard(tw: Twin) -> Dict[str, Any]:
    """A compact Home for one person at this moment: glucose + trend, 3 h back / 3 h ahead, the two
    coming-up cards, the six tiles in the page's fixed order, three learned chips."""
    spec = next(p for p in PERSONAS if p["patient_id"] == tw.patient_id)
    s, std = tw.state_now()
    lo, hi = target_range(tw)
    g = float(s.glucose)
    tone = "good" if lo <= g <= hi else ("bad" if g < lo else "warn")
    tr = home_view.trend(tw)
    mc = tw.cached("forecast:480", lambda: tw.forecast(horizon_min=480))
    n = 3 * 12 + 1
    hist = home_view.history(tw, 3.0)
    tiles = home_view.tiles(tw, details=False, always=("caffeine",))
    by = {t["key"]: t for t in tiles}
    six = [{k2: by[k][k2] for k2 in ("key", "icon", "label", "value", "unit", "value_text", "level", "status", "tone")} for k in TILE_ORDER if k in by]
    coming = [dict(c) for c in home_view.coming_up(tw, mc) if c["key"] in ("meal", "workout")]
    for c in coming:
        c["text"] = c["text"].replace("No low expected before then.", "").strip()
    chips = fact_chips(tw, 3)
    wk = query_history(tw, _iso(tw.now - timedelta(days=7)), _iso(tw.now), "average")
    return {
        "id": NAME_OF[spec["id"]], "name": spec["name"], "avatar": spec["avatar"], "sex": spec["sex"], "lifestyle": f"{spec['occupation']}, {spec['habit']}",
        "as_of": _iso(tw.now), "wall_now": _iso(tw.wall_now()),
        "glucose": _r(g), "tone": tone, "trend": tr["word"], "trend_arrow": tr["arrow"], "position": "in range" if lo <= g <= hi else ("low" if g < lo else "high"),
        "target_low": _r(lo), "target_high": _r(hi),
        "history": {"times": hist["times"], "display": hist["display"], "gaps": hist["gaps"]},
        "forecast": {"times": list(mc.times[:n]), "median": [_r(x, 1) for x in mc.median[:n]], "p10": [_r(x, 1) for x in mc.p10[:n]], "p90": [_r(x, 1) for x in mc.p90[:n]]},
        "coming_up": coming, "tiles": six, "chips": chips,
        "tir7": wk["time_in_range_pct"], "avg7": wk["average"], "lows7": wk["n_lows"],
        "carb_ratio": _r(spec["carb_ratio_g_per_u"]), "carb_ratio_text": f"1 unit covers {_r(spec['carb_ratio_g_per_u'])} g",
        "insulin_working": by["insulin"]["value"] if "insulin" in by else None, "recovery": by["recovery"]["value"] if "recovery" in by else None,
        "params": {k: _r(tw.params.get(k, 0), 3) for k in ("carb_ratio", "tau_carb", "si_tod0", "si_tod1", "si_tod2", "sleep_debt_coef", "exercise_mult")},
    }


def persona_stats() -> List[Dict[str, Any]]:
    """The three dashboards, in page order."""
    twins = get_twins()
    return [persona_dashboard(twins[pid]) for pid in PERSONA_IDS]


# ------------------------------------------------------------------ cache (frozen build) + live results

def cache_path(slug: str):
    return CACHE_DIR / f"{slug}.json"


def load_cache() -> Dict[str, Dict[str, Any]]:
    out = {}
    for b in BANK:
        p = cache_path(b["slug"])
        if p.exists():
            out[b["slug"]] = json.loads(p.read_text(encoding="utf-8"))
    return out


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")


def shift_dates(obj, delta: timedelta):
    """Every ISO datetime string inside a result moved by `delta` (whole days: the app's clock mapping)."""
    if not delta:
        return obj
    if isinstance(obj, dict):
        return {k: shift_dates(v, delta) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shift_dates(v, delta) for v in obj]
    if isinstance(obj, str) and _ISO_RE.match(obj):
        return _iso(datetime.fromisoformat(obj) + delta)
    return obj


class Live:
    """In-memory results for the current moment, refreshed by a background thread: the dashboards
    every time the twins tick (5 minutes), the six answers when they are older than REFRESH_MIN."""
    REFRESH_MIN = 12

    def __init__(self):
        self.lock = threading.Lock()
        self.personas: Optional[List[Dict[str, Any]]] = None
        self.results: Dict[str, Dict[str, Any]] = {}
        self.results_now: Optional[datetime] = None
        self.personas_now: Optional[datetime] = None
        self.thread: Optional[threading.Thread] = None
        self.stop = False

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {"personas": self.personas, "results": dict(self.results), "results_now": self.results_now, "personas_now": self.personas_now}

    def refresh_personas(self) -> None:
        stats = persona_stats()
        with self.lock:
            self.personas, self.personas_now = stats, twins_now()

    def refresh_results(self) -> None:
        twins = get_twins()
        now = twins_now()
        dash = {pid: persona_dashboard(tw) for pid, tw in twins.items()}
        for b in BANK:
            t0 = time.time()
            res = run_all(resolve_item(b, now), dashboards=dash)
            with self.lock:
                self.results[b["slug"]] = res
            log.info("compare: %s at %s -> %s (%.0f s)", b["slug"], _iso(now), res["divergence"]["classes"], time.time() - t0)
            time.sleep(0.2)   # let the app's own requests through between prompts
        with self.lock:
            self.results_now = now

    def loop(self) -> None:
        try:
            get_twins(); get_population_twin()
            self.refresh_personas()
            self.refresh_results()
            log.info("compare: live results ready")
        except Exception as ex:
            log.warning("compare warm-up failed: %s", type(ex).__name__, exc_info=True)
        while not self.stop:
            time.sleep(20)
            try:
                now = twins_now()
                if self.personas_now is None or now > self.personas_now:
                    self.refresh_personas()
                if self.results_now is None or (now - self.results_now) >= timedelta(minutes=self.REFRESH_MIN):
                    self.refresh_results()
            except Exception as ex:
                log.warning("compare refresh failed: %s", type(ex).__name__, exc_info=True)

    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self.loop, name="compare-live", daemon=True)
            self.thread.start()


LIVE = Live()


def bundle(parser: Dict[str, Any]) -> Dict[str, Any]:
    """What the page needs: the dashboards, the six results, the bank, the clock. Live results when they
    are ready; until then (and when the live clock is off) the frozen build, its dates mapped onto today."""
    snap = LIVE.snapshot() if LIVE_CLOCK else {"personas": None, "results": {}, "results_now": None, "personas_now": None}
    disk = load_cache()
    if LIVE_CLOCK:
        try:
            now = twins_now()
        except Exception:
            now = datetime.now().replace(second=0, microsecond=0)
        wall = _iso(datetime.now().replace(second=0, microsecond=0))
    else:
        now = COMPARE_NOW
        wall = _iso(now)
    delta = time_shift() if LIVE_CLOCK else timedelta(0)
    live_ready = bool(snap["results"]) and len(snap["results"]) == len(BANK) and snap["personas"] is not None
    results = snap["results"] if live_ready else {slug: shift_dates(res, delta) for slug, res in disk.items()}
    personas = snap["personas"]
    if personas is None:
        pp = CACHE_DIR / "personas.json"
        personas = shift_dates(json.loads(pp.read_text(encoding="utf-8")), delta) if pp.exists() else []
    return {"personas": personas, "results": results, "bank": bank_for(now), "now": _iso(now), "wall_now": wall,
            "live": live_ready, "parser": parser, "results_now": _iso(snap["results_now"]) if snap["results_now"] else None}


def nearest_cached(text: str, results: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """The bank prompt sharing the most keywords with the text (fallback when the engine is slow or fails)."""
    cache = results if results else (LIVE.snapshot()["results"] or load_cache())
    if not cache:
        return None
    words = set(re.findall(r"[a-z]+", text.lower())) - {"a", "an", "the", "i", "can", "have", "with", "at", "now", "right", "today", "tomorrow", "of", "for", "my", "some"}
    best, score = None, -1
    for slug, res in cache.items():
        bw = set(re.findall(r"[a-z]+", res["text"].lower()))
        s = len(words & bw)
        if s > score:
            best, score = res, s
    return best


# ------------------------------------------------------------------ live path with a timeout

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="compare")


def ask(text: str, timeout_s: float = 4.0) -> Dict[str, Any]:
    """A bank prompt from the live results (or the frozen cache); anything else live within the timeout,
    else the nearest cached prompt."""
    now = twins_now() if LIVE_CLOCK else COMPARE_NOW
    item = None
    try:
        item = item_from_text(text, now)
    except Exception as ex:
        log.warning("compare parse failed: %s", type(ex).__name__)
    if item is not None and item.get("slug"):
        results = LIVE.snapshot()["results"] if LIVE_CLOCK else {}
        cached = results.get(item["slug"]) or load_cache().get(item["slug"])
        if cached:
            return dict(cached, source="cache")
    if item is not None:
        fut = _POOL.submit(run_all, item, 100)
        try:
            res = fut.result(timeout=timeout_s)
            return dict(res, source="live")
        except FutureTimeout:
            log.warning("compare: engine timed out for %r; serving the nearest cached prompt", text)
        except Exception as ex:
            log.warning("compare: engine failed for %r (%s); serving the nearest cached prompt", text, type(ex).__name__)
    near = nearest_cached(text)
    if near is None:
        raise RuntimeError("no cached results")
    return dict(near, source="cached-fallback", asked=text)


def prewarm() -> None:
    """Build the twins and start the live refresher (live clock only; tests use the frozen cache)."""
    if LIVE_CLOCK:
        LIVE.start()
