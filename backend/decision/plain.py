"""Plain-language layer: turns the engine's cards (probabilities, variant names,
conditions) into the three-part answer the UI shows: a one-line recommendation,
a one- or two-sentence reason, and the tone (good / warn / bad / off).
No technical terms; probabilities become "unlikely / possible / likely / very likely"."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.schema.api import PermissionCard, PlanResponse, ChangeResponse


def likelihood(p: Optional[float]) -> str:
    if p is None:
        return "uncertain"
    if p < 0.05:
        return "unlikely"
    if p < 0.20:
        return "possible"
    if p < 0.50:
        return "likely"
    return "very likely"


def _t(iso: Optional[str]) -> str:
    """Clock time like 22:00 without seconds."""
    return iso[11:16] if iso and len(iso) >= 16 else ""


def _when(iso: str, now: datetime) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return _t(iso)
    days = (d.date() - now.date()).days
    day = ("tonight" if d.hour >= 17 else "today") if days == 0 else "tomorrow" if days == 1 else d.strftime("%A")
    return f"{day} at {d.strftime('%H:%M')}"


def event_phrase(e: Dict[str, Any]) -> str:
    """'2 beers', 'a large coffee', 'a 30 min run'..."""
    lbl = (e.get("label") or "").strip()
    t = e.get("type")
    if lbl:
        return lbl
    if t == "exercise":
        return f"a {int(e.get('duration_min') or 30)} min workout"
    if t == "alcohol":
        n = max(1, round(float(e.get("alcohol_g") or 14) / 14.0))
        return f"{n} drink{'s' if n > 1 else ''}"
    if t == "caffeine":
        return "a coffee"
    if t == "meal":
        return f"a meal with {int(e.get('carbs_g') or 0)} g carbs"
    return t or "that"


def understood_line(e: Dict[str, Any], now: datetime) -> str:
    return f"Understood: {event_phrase(e)} {_when(e.get('start_time', ''), now)}"


CONDITION_PLAIN = {
    "delay_1h": "wait about an hour first",
    "halve": "have half as much",
    "pre_workout_snack_20g": "eat a small snack (about 20 g of carbs) 15 minutes before",
    "fast_carbs_15g": "have 15 g of fast carbs first",
    "halve_plus_carbs": "have half as much and 15 g of carbs before bed",
    "fast_carbs_now_15g": "have 15 g of fast carbs now",
    "alternative_window": "move it to a better time",
}
HEADLINE_COND = {
    "delay_1h": "Yes, but wait an hour", "halve": "Yes, but less", "pre_workout_snack_20g": "Yes, with a snack",
    "fast_carbs_15g": "Yes, with a snack", "halve_plus_carbs": "Yes, less and a snack", "fast_carbs_now_15g": "Yes, after a snack",
}


def condition_plain(card: PermissionCard) -> str:
    name = card.variant_name or ""
    if card.proposed and card.proposed.type == "alcohol" and name == "fast_carbs_15g":
        return "eat 15 g of carbs before bed (no insulin for it)"
    if name in CONDITION_PLAIN:
        return CONDITION_PLAIN[name]
    c = (card.condition or "").strip()
    c = re.sub(r"\(?P\(hypo\)[^)]*\)?", "", c)          # strip probabilities
    c = re.sub(r"\s+", " ", c).strip(" ;:,")
    return c


def _alt(card: PermissionCard) -> Optional[Dict[str, Any]]:
    for v in card.variants or []:
        if v.get("name") == "alternative_window":
            return v
    return None


def _v(card: PermissionCard, name: str) -> Optional[Dict[str, Any]]:
    for v in card.variants or []:
        if v.get("name") == name:
            return v
    return None


def permission_plain(card: PermissionCard, now: datetime) -> Dict[str, Any]:
    e = card.proposed.model_dump() if card.proposed else {}
    what = event_phrase(e)
    typ = e.get("type")
    nothing, prop = _v(card, "do_nothing"), _v(card, "proposed")
    p_prop = prop["p_hypo"] if prop else card.p_hypo
    p_none = nothing["p_hypo"] if nothing else None
    min_prop = prop.get("min_glucose") if prop else None
    low_word = "low" if typ != "alcohol" else "low overnight"
    if card.verdict == "request_data":
        return {"headline": "Need a fresh reading first", "tone": "off",
                "reason": "Your sensor data is too old to judge this safely. Check your sensor and ask again."}
    if card.verdict == "escalate":
        return {"headline": "Check with your care team", "tone": "bad",
                "reason": card.condition or "Something in your recent readings needs a person, not an app."}
    if card.verdict == "approved":
        head = {"exercise": "Go for it", "meal": "Enjoy it", "alcohol": "Go ahead", "caffeine": "Go ahead"}.get(typ, "Go ahead")
        reason = f"Going {low_word} after {what} is {likelihood(p_prop)}."
        if min_prop:
            reason += f" The lowest we expect is about {int(round(min_prop))} mg/dL."
        return {"headline": head, "tone": "good", "reason": reason}
    if card.verdict == "approved_with_condition":
        cond = condition_plain(card)
        head = HEADLINE_COND.get(card.variant_name or "", "Yes, with one change")
        if p_none is not None and p_none >= 0.05 and p_prop <= p_none + 0.02:
            # the proposal itself is harmless; the person is already trending low
            plural = bool(re.match(r"^([2-9]|\d{2,})", what)) or what.endswith("s")
            reason = f"{what[0].upper() + what[1:]} {'add' if plural else 'adds'} no risk {'by themselves' if plural else 'by itself'}, but you are already heading {low_word}: a low is {likelihood(p_none)} in the next few hours anyway. "
            reason += f"Best to {cond}, then go ahead."
        else:
            reason = f"On its own, {what} makes going {low_word} {likelihood(p_prop)}. If you {cond}, it becomes {likelihood(card.p_hypo)}."
        alt = _alt(card)
        if alt and typ == "exercise" and alt.get("start"):
            reason += f" A good time to move it to would be {_when(alt['start'], now)}."
        return {"headline": head, "tone": "warn", "reason": reason}
    # denied
    alt = _alt(card)
    head = "Better to wait" if (alt and typ == "exercise") else ("Better not tonight" if now.hour >= 17 else "Better not right now")
    best_cond = condition_plain(card).split(";")[0]
    reason = f"Going {low_word} after {what} is {likelihood(p_prop)}"
    reason += f", and even if you {best_cond} it stays {likelihood(card.p_hypo)}." if best_cond else "."
    if alt and alt.get("start"):
        reason += f" A better time would be {_when(alt['start'], now)}."
    return {"headline": head, "tone": "bad", "reason": reason}


def plan_plain(plan: PlanResponse, now: datetime) -> Dict[str, Any]:
    if not plan.workout_start:
        return {"headline": "No good workout slot found", "tone": "warn", "reason": "Every slot tomorrow carries a real chance of a low; a snack before exercising would be needed."}
    head = f"Best time to exercise: {_when(plan.workout_start, now)}"
    parts = []
    if plan.snack_time:
        parts.append(f"Have a small snack at {_t(plan.snack_time)}.")
    if plan.drink_cutoff:
        parts.append(f"Last drink by {_t(plan.drink_cutoff)}.")
    parts.append(f"Going low around the workout is {likelihood(plan.p_hypo)}.")
    tone = "good" if plan.p_hypo < 0.05 else "warn" if plan.p_hypo < 0.2 else "bad"
    return {"headline": head, "tone": tone, "reason": " ".join(parts)}


CHANGE_NAMES = {"morning_workouts": "moving workouts to the morning", "cut_caffeine": "cutting caffeine",
                "drink_fridays_only": "drinking on Fridays only", "fasting_16_8": "skipping breakfast (16:8 fasting)", "no_change": "changing nothing"}


def change_plain(resp: ChangeResponse) -> Dict[str, Any]:
    s = {r["key"]: r for r in resp.summary_30d}
    what = CHANGE_NAMES.get(resp.change, resp.change.replace("_", " "))
    head = {"merged": "Worth doing", "merged_with_changes": "Worth doing, with a snack", "rejected": "Not recommended"}[resp.verdict]
    tone = {"merged": "good", "merged_with_changes": "warn", "rejected": "bad"}[resp.verdict]
    bits = []
    if "tir" in s:
        bits.append(f"time in range goes from {s['tir']['before']:.0f}% to {s['tir']['after']:.0f}%")
    if "lows" in s:
        bits.append(f"predicted lows from {s['lows']['before']:.0f} to {s['lows']['after']:.0f} a week")
    reason = f"Over 30 days of {what}, " + " and ".join(bits) + "." if bits else resp.reason
    if resp.verdict == "merged_with_changes":
        reason += " A 20 g snack before each new workout keeps the lows down."
    return {"headline": head, "tone": tone, "reason": reason}
