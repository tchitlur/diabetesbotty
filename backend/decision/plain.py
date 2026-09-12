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


def fmt12(x) -> str:
    """12-hour clock: '7:30 pm', '12:05 am'."""
    d = datetime.fromisoformat(x) if isinstance(x, str) else x
    if d is None:
        return ""
    h = d.hour % 12 or 12
    return f"{h}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"


def fmt_date(x) -> str:
    """'Sat, Sep 12'."""
    d = datetime.fromisoformat(x) if isinstance(x, str) else x
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}"


def _t(iso: Optional[str]) -> str:
    return fmt12(iso) if iso and len(iso) >= 16 else ""


def _when(iso: str, now: datetime) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return _t(iso)
    days = (d.date() - now.date()).days
    day = ("tonight" if d.hour >= 17 else "today") if days == 0 else "tomorrow" if days == 1 else d.strftime("%A")
    return f"{day} at {fmt12(d)}"


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


CAUSE = {
    "alcohol": "alcohol stops your liver releasing sugar for hours",
    "exercise": "exercise burns through sugar faster",
    "meal": "the carbs digest",
    "caffeine": "caffeine makes insulin work a little less well",
}


def _cause_text(cause_event: Optional[Dict[str, Any]]) -> str:
    if not cause_event:
        return ""
    lbl = (cause_event.get("label") or cause_event.get("type") or "").replace("bolus for ", "the insulin for ")
    return f" from {lbl} at {_t(cause_event.get('start_time'))}" if lbl else ""


def permission_plain(card: PermissionCard, now: datetime, cause_event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Headline + reason built from the simulation results: the predicted peak or low with its
    time, what causes it, and what the condition changes."""
    e = card.proposed.model_dump() if card.proposed else {}
    what = event_phrase(e)
    What = what[0].upper() + what[1:]
    typ = e.get("type")
    nothing, prop = _v(card, "do_nothing"), _v(card, "proposed")
    best = _v(card, card.variant_name) if card.variant_name else None
    p_prop = prop["p_hypo"] if prop else card.p_hypo
    p_none = nothing["p_hypo"] if nothing else None
    if card.verdict == "request_data":
        return {"headline": "Need a fresh reading first", "tone": "off",
                "reason": "Your sensor data is too old to judge this safely. Check your sensor and ask again."}
    if card.verdict == "escalate":
        return {"headline": "Check with your care team", "tone": "bad",
                "reason": card.condition or "Something in your recent readings needs a person, not an app."}
    if not prop:
        return {"headline": card.verdict.replace("_", " "), "tone": "off", "reason": card.condition or ""}

    def _at(iso: str) -> str:
        # same day: just the time; another day: "tomorrow at 8:20 am"
        try:
            return _t(iso) if datetime.fromisoformat(iso).date() == now.date() else _when(iso, now)
        except (ValueError, TypeError):
            return _t(iso)

    def _same_day(iso: str) -> bool:
        try:
            return datetime.fromisoformat(iso).date() == now.date()
        except (ValueError, TypeError):
            return True

    def peak_clause(v):
        return f"about {int(round(v['peak']))} " + (f"by {_t(v['peak_time'])}" if _same_day(v['peak_time']) else _when(v['peak_time'], now).replace(" at ", " by "))

    def low_clause(v):
        return f"about {int(round(v['nadir']))} " + (f"around {_t(v['nadir_time'])}" if _same_day(v['nadir_time']) else _when(v['nadir_time'], now).replace(" at ", " around "))

    cause = CAUSE.get(typ, "")
    rises = typ == "meal" and prop["peak"] - (nothing["peak"] if nothing else prop["peak"]) > 8
    drops = (nothing["nadir"] if nothing else prop["nadir"]) - prop["nadir"] > 8
    if card.verdict == "approved":
        head = {"exercise": "Go for it", "meal": "Enjoy it", "alcohol": "Go ahead", "caffeine": "Go ahead"}.get(typ, "Go ahead")
        if rises:
            back = {"nadir": prop.get("after_peak", prop["nadir"]), "nadir_time": prop.get("after_peak_time", prop["nadir_time"])}
            reason = f"{What} would take you to {peak_clause(prop)} as {cause}, then back to {low_clause(back)}."
        elif drops:
            reason = f"{What} would bring you down to {low_clause(prop)} because {cause}, which is still a safe margin."
        else:
            reason = f"{What} barely moves you: you stay between about {int(round(prop['nadir']))} and {int(round(prop['peak']))} over the next few hours."
        reason += f" A low is {likelihood(p_prop)}."
        return {"headline": head, "tone": "good", "reason": reason}
    cond = condition_plain(card)
    if card.verdict == "approved_with_condition":
        head = HEADLINE_COND.get(card.variant_name or "", "Yes, with one change")
        if p_none is not None and p_none >= 0.05 and p_prop <= p_none + 0.02:
            # the proposal is not the problem: a low is already coming
            reason = (f"Even without {what}, the model expects a low of {low_clause(nothing)}{_cause_text(cause_event)}, and {what} does not change that. "
                      f"If you {cond}, the low point rises to about {int(round(best['nadir']))}." if best else
                      f"Even without {what}, the model expects a low of {low_clause(nothing)}{_cause_text(cause_event)}; {cond} first.")
        else:
            reason = f"On its own, {what} would drop you to {low_clause(prop)} because {cause}."
            if best:
                reason += f" If you {cond}, the low point becomes about {int(round(best['nadir']))} and a low is {likelihood(card.p_hypo)}."
        alt = _alt(card)
        if alt and typ == "exercise" and alt.get("start"):
            reason += f" A better time would be {_when(alt['start'], now)}."
        return {"headline": head, "tone": "warn", "reason": reason}
    alt = _alt(card)
    head = "Better to wait" if (alt and typ == "exercise") else ("Better not tonight" if now.hour >= 17 else "Better not right now")
    if float(prop.get("p_hyper", 0.0) or 0.0) >= 0.2 and p_prop < 0.05:
        # denied for a high, not a low
        reason = f"{What} would take you to {peak_clause(prop)} as {cause}; a high (over 250) is {likelihood(float(prop['p_hyper']))}."
        if best and cond and best is not prop:
            reason += f" Even if you {cond}, the peak is about {int(round(best['peak']))}."
        return {"headline": head, "tone": "bad", "reason": reason}
    reason = f"{What} would drop you to {low_clause(prop)} because {cause}"
    if best and cond:
        reason += f"; even if you {cond} it only lifts to about {int(round(best['nadir']))}, so a low stays {likelihood(card.p_hypo)}."
    else:
        reason += "."
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
