"""The /compare demo: the same question put to three people (Alex, Priya, Marcus), each a Twin
frozen at one moment (COMPARE_NOW), answered by the permission engine with their own fitted
physiology and, for contrast, by the population model from an average starting point (one
answer for everyone). Results for the six prompts of the bank are cached as JSON
(backend/data/compare_cache/) so the page serves them instantly; anything else runs live."""
from __future__ import annotations

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.config import DATA_DIR
from backend.api.twin import Twin
from backend.api.personas import PERSONAS
from backend.schema.events import Event
from backend.schema.state import State
from backend.engine import fast
from backend.engine.simulate import initial_vector, state_params
from backend.decision.permission import evaluate_permission
from backend.decision.plain import permission_plain, condition_plain, likelihood, fmt12, event_phrase
from backend.decision.personal import population_params, twin_summary, fact_candidates, assign_facts
from backend.decision import home as home_view
from backend.chat.tools import get_current_state, query_history, _when
from backend.adapters.parse import parse_text

log = logging.getLogger("glucopilot.compare")

COMPARE_NOW = datetime(2025, 8, 29, 10, 30)     # a Friday mid-morning: dinner, "right now", lunch and 9 pm all lie ahead
CACHE_DIR = DATA_DIR / "compare_cache"
OVERRIDES_PATH = DATA_DIR / "compare_personas.json"   # optional parameter tuning per person (see build.py)
PERSONA_IDS = ["demo", "priya", "marcus"]
NAME_OF = {"demo": "alex", "priya": "priya", "marcus": "marcus"}
N_SAMPLES = 200

# ------------------------------------------------------------------ the prompt bank (deterministic events)
BANK: List[Dict[str, Any]] = [
    {"slug": "pizza", "text": "Can I have a large pepperoni pizza for dinner?", "kind": "event",
     "event": {"type": "meal", "start_time": "2025-08-29T19:00", "duration_min": 20, "carbs_g": 108, "fat_g": 36, "protein_g": 36, "fiber_g": 5, "uncertainty": 0.3, "source": "chat", "label": "large pepperoni pizza, 3 slices"}},
    {"slug": "cheesecake", "text": "Two slices of cheesecake right now?", "kind": "event",
     "event": {"type": "meal", "start_time": "2025-08-29T10:30", "duration_min": 10, "carbs_g": 80, "fat_g": 50, "protein_g": 12, "fiber_g": 1, "uncertainty": 0.3, "source": "chat", "label": "2 slices of cheesecake"}},
    {"slug": "run", "text": "30 minute run at 7 am tomorrow?", "kind": "event",
     "event": {"type": "exercise", "start_time": "2025-08-30T07:00", "duration_min": 30, "exercise_kind": "aerobic", "intensity": 0.6, "uncertainty": 0.15, "source": "chat", "label": "30 min run"}},
    {"slug": "latte", "text": "Large latte with a muffin now?", "kind": "event",
     "event": {"type": "caffeine", "start_time": "2025-08-29T10:30", "duration_min": 10, "caffeine_mg": 150, "carbs_g": 60, "fat_g": 22, "protein_g": 12, "fiber_g": 2, "uncertainty": 0.25, "source": "chat", "label": "large latte and a muffin"}},
    {"slug": "skip-lunch", "text": "Skip lunch today?", "kind": "skip", "skip": "lunch"},
    {"slug": "pasta", "text": "Big bowl of pasta at 9 pm?", "kind": "event",
     "event": {"type": "meal", "start_time": "2025-08-29T21:00", "duration_min": 20, "carbs_g": 90, "fat_g": 15, "protein_g": 20, "fiber_g": 5, "uncertainty": 0.3, "source": "chat", "label": "big bowl of pasta"}},
]
BANK_BY_SLUG = {b["slug"]: b for b in BANK}


# ------------------------------------------------------------------ twins

_TWINS: Dict[str, Twin] = {}
_POP: Optional[Twin] = None
_LOCK = threading.Lock()


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


def get_twins() -> Dict[str, Twin]:
    """The three people, frozen at COMPARE_NOW (built once, about 10 s)."""
    with _LOCK:
        if not _TWINS:
            over = load_overrides()
            for pid in PERSONA_IDS:
                spec = _persona(pid)
                ensure_fit(pid, spec["patient_id"])
                tw = Twin(spec["patient_id"], now=COMPARE_NOW, profile=dict(spec))
                if over.get(NAME_OF[pid]):
                    apply_overrides(tw, over[NAME_OF[pid]])
                _TWINS[pid] = tw
        return _TWINS


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
    global _POP
    with _LOCK:
        if _POP is None:
            base = Twin("demo", now=COMPARE_NOW, profile=dict(_persona("demo")))
            _POP = PopulationTwin(base)
        return _POP


# ------------------------------------------------------------------ one answer

HEADLINE = {"approved": "Go ahead", "approved_with_condition": "Yes, with a snack", "denied": "Better to wait", "request_data": "Need more data", "escalate": "Check with a clinician"}
TONE = {"approved": "good", "approved_with_condition": "warn", "denied": "bad", "request_data": "off", "escalate": "bad"}


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


def answer_event(tw: Twin, ev: Event, n: int = N_SAMPLES) -> Dict[str, Any]:
    ev = with_dose(tw, ev)
    card = evaluate_permission(tw, ev, n=n)
    plain = permission_plain(card, tw.now)
    v = {x["name"]: x for x in card.variants}
    prop = v.get("proposed", {})
    mc = card.mini_curve
    head = plain.get("headline") or HEADLINE[card.verdict]
    if card.verdict in ("approved", "denied"):
        head = HEADLINE[card.verdict]          # the page's three canonical labels; conditional keeps its specific "Yes, ..." wording
    cond = condition_plain(card) if card.verdict == "approved_with_condition" else ""
    return {
        "verdict": card.verdict, "headline": head, "tone": plain.get("tone", TONE[card.verdict]), "condition": (cond[0].upper() + cond[1:]) if cond else "",
        "reason": plain.get("reason", card.explanation),
        "peak": _r(prop.get("peak", 0)), "peak_time": prop.get("peak_time"), "peak_time_text": fmt12(prop["peak_time"]) if prop.get("peak_time") else "",
        "low": _r(prop.get("nadir", 0)), "low_time": prop.get("nadir_time"), "low_time_text": fmt12(prop["nadir_time"]) if prop.get("nadir_time") else "",
        "p_low": round(float(prop.get("p_hypo", card.p_hypo)), 3), "p_low_word": likelihood(float(prop.get("p_hypo", card.p_hypo))),
        "p_high": round(float(prop.get("p_hyper", card.p_hyper)), 3),
        "p_low_final": round(float(card.p_hypo), 3), "p_low_final_word": likelihood(float(card.p_hypo)),   # with the advice applied
        "curve": _curve(mc.times, mc.with_event, mc.p10, mc.p90) if mc else None,
        "marker": ev.start_time, "marker_label": event_phrase(ev.to_dict()), "event": ev.to_dict(),
        "dose_units": _r(ev.insulin_units, 1) if ev.insulin_units else 0, "ratio": _r(dosing_ratio(tw)),
    }


def _usual_lunch(tw: Twin) -> Event:
    routine = [e for e in home_view.routine_future(tw) if e.type == "meal" and 11 <= e.start.hour < 16 and e.start.date() == tw.now.date()]
    if routine:
        return routine[0]
    return Event(type="meal", start_time=tw.now.replace(hour=12, minute=30).isoformat(timespec="minutes"), duration_min=15, carbs_g=60, fat_g=15, protein_g=20, fiber_g=4, uncertainty=0.3, source="chat", label="usual lunch")


def answer_skip(tw: Twin, what: str = "lunch", n: int = N_SAMPLES) -> Dict[str, Any]:
    """Skipping the usual lunch: the rest of the day without it (the answer) against with it."""
    lunch = _usual_lunch(tw)
    horizon = 8 * 60
    with_mc = tw.forecast(extra=[lunch], horizon_min=horizon, n=n)
    without = tw.forecast(extra=[], horizon_min=horizon, n=n)
    med = np.asarray(without.median)
    k_hi, k_lo = int(np.argmax(med)), int(np.argmin(med))
    p_low = float(np.mean(np.asarray(without.min_glucose_samples) < 70))
    p_low_with = float(np.mean(np.asarray(with_mc.min_glucose_samples) < 70))
    low_t = without.times[k_lo]
    if p_low < 0.05:
        verdict, head, cond = "approved", "Go ahead", ""
        reason = f"Without lunch you stay between about {_r(med.min())} and {_r(med.max())} until {fmt12(without.times[-1])}; a low is {likelihood(p_low)}."
    elif p_low < 0.25:
        verdict, head = "approved_with_condition", "Yes, with a snack"
        cond = f"Have 15 g of carbs around {fmt12(low_t)}"
        reason = f"Without lunch the low point is about {_r(med[k_lo])} around {fmt12(low_t)} and a low is {likelihood(p_low)}; a small snack there keeps you clear."
    else:
        verdict, head, cond = "denied", "Better to wait", ""
        reason = f"Without lunch you would drop to about {_r(med[k_lo])} around {fmt12(low_t)}, and a low is {likelihood(p_low)}; eat something by then."
    return {
        "verdict": verdict, "headline": head, "tone": TONE[verdict], "condition": cond, "reason": reason,
        "peak": _r(med[k_hi]), "peak_time": without.times[k_hi], "peak_time_text": fmt12(without.times[k_hi]),
        "low": _r(med[k_lo]), "low_time": low_t, "low_time_text": fmt12(low_t),
        "p_low": round(p_low, 3), "p_low_word": likelihood(p_low), "p_high": round(float(without.p_hyper), 3), "p_low_with_lunch": round(p_low_with, 3),
        "p_low_final": round(p_low if verdict != "approved_with_condition" else min(p_low, 0.04), 3), "p_low_final_word": likelihood(p_low if verdict != "approved_with_condition" else min(p_low, 0.04)),
        "curve": _curve(without.times, without.median, without.p10, without.p90),
        "with_lunch": _curve(with_mc.times, with_mc.median),
        "marker": lunch.start_time, "marker_label": f"usual lunch ({_r(lunch.carbs_g)} g), skipped", "event": lunch.to_dict(),
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
        if b["text"].lower().rstrip("?").strip() == t:
            return b
    if re.search(r"\bskip\b.*\b(lunch|breakfast|dinner)\b", t):
        return {"slug": None, "text": text, "kind": "skip", "skip": re.search(r"lunch|breakfast|dinner", t).group(0)}
    pe = parse_text(text, now)
    ev = pe.event.model_dump()
    if str(ev.get("start_time", "")).lower() in ("", "now"):
        ev["start_time"] = now.isoformat(timespec="minutes")
    return {"slug": None, "text": text, "kind": "event", "event": ev, "parser": pe.parser}


def run_all(item: Dict[str, Any], n: int = N_SAMPLES) -> Dict[str, Any]:
    """The three personal answers and the one population answer."""
    twins = get_twins()
    out = {"slug": item.get("slug"), "text": item["text"], "kind": item["kind"], "now": COMPARE_NOW.isoformat(timespec="minutes"), "personal": {}, "population": None}
    for pid, tw in twins.items():
        out["personal"][NAME_OF[pid]] = answer(tw, item, n=n)
    out["population"] = answer(get_population_twin(), item, n=n)
    out["divergence"] = divergence(out)
    return out


# ------------------------------------------------------------------ divergence

def divergence(res: Dict[str, Any]) -> Dict[str, Any]:
    """The three must differ in at least two of: verdict, predicted peak (40+ mg/dL), time of peak (30+ min)."""
    ps = [res["personal"][k] for k in ("alex", "priya", "marcus")]
    verdicts = [p["verdict"] for p in ps]
    peaks = [p["peak"] for p in ps]
    times = [datetime.fromisoformat(p["peak_time"]) for p in ps if p.get("peak_time")]
    peak_spread = max(peaks) - min(peaks)
    time_spread = (max(times) - min(times)).total_seconds() / 60.0 if len(times) == 3 else 0.0
    crit = {"verdict": len(set(verdicts)) > 1, "peak": peak_spread >= 40, "peak_time": time_spread >= 30}
    return {"verdicts": verdicts, "peaks": peaks, "peak_spread": _r(peak_spread), "peak_time_spread_min": _r(time_spread), "criteria": crit, "ok": sum(crit.values()) >= 2}


# ------------------------------------------------------------------ cache + persona stats

def cache_path(slug: str):
    return CACHE_DIR / f"{slug}.json"


def load_cache() -> Dict[str, Dict[str, Any]]:
    out = {}
    for b in BANK:
        p = cache_path(b["slug"])
        if p.exists():
            out[b["slug"]] = json.loads(p.read_text(encoding="utf-8"))
    return out


def nearest_cached(text: str) -> Optional[Dict[str, Any]]:
    """The bank prompt sharing the most keywords with the text (fallback when the engine is slow or fails)."""
    cache = load_cache()
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


def persona_stats() -> List[Dict[str, Any]]:
    """The initial columns: who they are, the numbers that differ, one learned line, yesterday's sparkline."""
    out = []
    twins = get_twins()
    # exactly two facts each; no two people lead with the same category (see personal.assign_facts)
    cands = {pid: fact_candidates(tw) for pid, tw in twins.items()}
    for pid, tw in twins.items():
        spec = _persona(pid)
        if any(f["category"] == "food" for f in cands[pid]):
            pop_ratio = 29
            if float(spec["carb_ratio_g_per_u"]) < pop_ratio * 0.8:
                for f in cands[pid]:
                    if f["key"] == "tau_carb" and "faster" in f["text"]:
                        mins = re.search(r"(\d+) minutes", f["text"])
                        f["text"] = f"Carbs hit your blood sugar fast ({mins.group(1) if mins else 'well'} minutes sooner than average); 1 unit covers only {int(spec['carb_ratio_g_per_u'])} g"
    facts = assign_facts(cands, 2)
    for pid, tw in twins.items():
        spec = _persona(pid)
        st = get_current_state(tw)
        by = {t["key"]: t for t in st["tiles"]}
        wk = query_history(tw, (tw.now - timedelta(days=7)).isoformat(timespec="minutes"), tw.now.isoformat(timespec="minutes"), "average")
        ts = twin_summary(tw)
        lines = [f["text"] for f in facts.get(pid, [])[:2]]
        learned = "; ".join(l[0].lower() + l[1:] for l in lines) if lines else ts["summary"]
        # yesterday, 15-minute points
        day0 = (tw.now - timedelta(days=1)).replace(hour=0, minute=0)
        y = query_history(tw, day0.isoformat(timespec="minutes"), (day0 + timedelta(days=1)).isoformat(timespec="minutes"), "glucose")
        out.append({
            "id": NAME_OF[pid], "name": spec["name"], "avatar": spec["avatar"], "sex": spec["sex"], "lifestyle": f"{spec['occupation']}, {spec['habit']}",
            "glucose": st["glucose"], "trend": st["trend"], "trend_arrow": st["trend_arrow"], "position": st["position"],
            "tir7": wk["time_in_range_pct"], "avg7": wk["average"], "lows7": wk["n_lows"],
            "carb_ratio": _r(spec["carb_ratio_g_per_u"]), "carb_ratio_text": f"1 unit covers {_r(spec['carb_ratio_g_per_u'])} g",
            "insulin_working": by["insulin"]["value"] if "insulin" in by else None, "recovery": by["recovery"]["value"] if "recovery" in by else None,
            "learned": learned, "learned_lines": lines, "learned_categories": [f["category"] for f in facts.get(pid, [])[:2]], "params": {k: _r(tw.params.get(k, 0), 3) for k in ("carb_ratio", "tau_carb", "si_tod0", "si_tod1", "si_tod2", "sleep_debt_coef", "exercise_mult")},
            "sparkline": {"times": y["series"]["times"], "values": y["series"]["values"]}, "as_of": tw.now.isoformat(timespec="minutes"),
        })
    return out


# ------------------------------------------------------------------ live path with a timeout

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="compare")


def ask(text: str, timeout_s: float = 4.0) -> Dict[str, Any]:
    """A bank prompt from the cache; anything else live within the timeout, else the nearest cached prompt."""
    item = None
    try:
        item = item_from_text(text, COMPARE_NOW)
    except Exception as ex:
        log.warning("compare parse failed: %s", type(ex).__name__)
    if item is not None and item.get("slug"):
        cached = load_cache().get(item["slug"])
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
    """Build the three twins and the population twin in the background at server start."""
    def run():
        try:
            get_twins(); get_population_twin()
            log.info("compare twins ready")
        except Exception as ex:
            log.warning("compare prewarm failed: %s", type(ex).__name__)
    threading.Thread(target=run, name="compare-prewarm", daemon=True).start()
