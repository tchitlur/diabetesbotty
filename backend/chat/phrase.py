"""Templated sentences built directly from tool results. Used by the local fallback (no
Gemini key) and as the replacement answer whenever Gemini's text fails the grounding check.
Every number here is read from the result dict; nothing is invented."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _n(x, d: int = 0) -> str:
    if x is None:
        return "?"
    return f"{float(x):.{d}f}"


def state(r: Dict[str, Any], focus: Optional[str] = None) -> str:
    s = f"Your glucose is {r['glucose']} mg/dL and {r['trend']}"
    if r["trend"] != "steady":
        s += f" ({'+' if r['trend_mgdl_per_hour'] > 0 else ''}{r['trend_mgdl_per_hour']} mg/dL per hour)"
    s += f", {r['position']} (target {r['target_low']}-{r['target_high']}), as of {r['as_of_text']}."
    if r.get("sensor_stale"):
        s += f" The sensor has not reported for {r['sensor_staleness_min']} minutes, so treat this as stale."
    by = {t["key"]: t for t in r.get("tiles", [])}
    if focus and focus in by:
        t = by[focus]
        return s + f" {t['label']}: {t['value_text']} ({t['status']}). {t['note']}"
    top = [f"{t['label'].lower()} {t['value_text']} ({t['status']})" for t in r.get("tiles", [])[:3]]
    if top:
        s += " Right now: " + "; ".join(top) + "."
    return s


def forecast(r: Dict[str, Any]) -> str:
    h = r["hours"]
    hh = f"{h:g} hour{'s' if h != 1 else ''}"
    s = f"In {hh} (by {r['to_text']}) the model expects about {r['expected_at_end']} mg/dL, likely between {r['range_at_end'][0]} and {r['range_at_end'][1]}."
    if r["peak"]["value"] - r["now_glucose"] > 8 and r["peak"]["time"] != r["from"]:
        s += f" It peaks at about {r['peak']['value']} around {r['peak']['time_text']}"
        if r["low"]["value"] < r["peak"]["value"] - 8 and r["low"]["time"] != r["from"]:
            s += f" and dips to about {r['low']['value']} around {r['low']['time_text']}"
        s += "."
    elif r["low"]["value"] < r["now_glucose"] - 8 and r["low"]["time"] != r["from"]:
        s += f" The low point is about {r['low']['value']} around {r['low']['time_text']}."
    s += f" A low (under 70) before then is {r['p_low_word']} ({r['p_low_pct']}%)"
    if r["p_high_pct"] >= 5:
        s += f"; a high (over 250) is {r['p_high_word']} ({r['p_high_pct']}%)"
    s += "."
    if r.get("median_first_below_70_text"):
        s += f" The middle path crosses 70 around {r['median_first_below_70_text']}."
    return s


def explain(r: Dict[str, Any], focus: Optional[str] = None) -> str:
    p = r["pending"]
    if focus == "insulin":
        s = f"{p['insulin_on_board_u']} U of insulin is still to act (plasma insulin {p['plasma_insulin_mU_L']} mU/L, {p['insulin_vs_basal']}x your basal level)"
        s += ", and its action is peaking now." if p["insulin_peaked_already"] else f", peaking in about {p['insulin_peak_in_min']} min."
        if p.get("last_bolus"):
            s += f" Your last dose was {p['last_bolus']['units']} U at {p['last_bolus']['time_text']} ({p['last_bolus']['minutes_ago']} min ago)."
        return s
    if focus == "carbs":
        if p["carbs_g"] <= 3:
            return "Nothing is left to digest: the model has no carbs in your gut right now."
        s = f"About {p['carbs_g']} g of carbs are still digesting, absorbing at about {p['carbs_absorbing_g_per_hour']} g per hour"
        if p["carbs_peak_in_min"] and p["carbs_peak_in_min"] > 5:
            s += f"; they hit fastest in about {p['carbs_peak_in_min']} min"
        if p["carbs_done_in_min"]:
            s += f" and are mostly absorbed in about {p['carbs_done_in_min']} min"
        s += "."
        if p["absorption_slowdown"] > 1.05:
            s += f" Fat and fibre are slowing them ({p['absorption_slowdown']:.1f}x)."
        if p.get("last_meal"):
            s += f" Last meal: {p['last_meal']['label']} ({p['last_meal']['carbs_g']} g) at {p['last_meal']['time_text']}."
        return s
    return r["summary"]


def history(r: Dict[str, Any], question: str = "") -> str:
    q = question.lower()
    m = r["metric"]
    win = f"between {r['start_text']} and {r['end_text']}"
    if m == "glucose" and r.get("window_hours", 0) <= 1 and r.get("reading_nearest_start"):
        n = r["reading_nearest_start"]
        return f"At {n['time_text']} your glucose was {n['value']} mg/dL."
    if m == "lows" or "low" in q:
        if "last" in q and not ("week" in q or "how many" in q):
            if r.get("last_low"):
                ll = r["last_low"]
                return f"Your last low was {r['last_low_when']}, down to {ll['min']} mg/dL (it started at {ll['start_text']} on {ll['date_text']})."
            return "No low (under 70) in the last 30 days."
        s = f"You had {r['n_lows']} low{'s' if r['n_lows'] != 1 else ''} (under 70) {win}"
        if r.get("last_low"):
            s += f"; the last one was {r['last_low_when']}, down to {r['last_low']['min']}"
        s += f". Time below 70: {_n(r['time_below_70_pct'], 1)}%."
        return s
    if m in ("average", "tir"):
        return (f"Your average {win} is {r['average']} mg/dL (spread {r['sd']}), with {r['time_in_range_pct']}% of readings in 70-180, "
                f"{_n(r['time_below_70_pct'], 1)}% below 70 and {_n(r['time_above_180_pct'], 1)}% above 180, over {r['n_readings']} readings.")
    if m == "sleep":
        if not r["sleep"]:
            return f"No sleep record {win}."
        x = r["sleep"][-1]
        return f"You slept {x['hours']} hours (to bed {x['bed_text']}, up at {x['wake_text']}, night of {x['night_of']})."
    if m in ("events", "carbs", "insulin", "exercise", "caffeine", "alcohol"):
        evs = r["events"]
        if m == "events":
            evs = [e for e in evs if e["type"] in ("meal", "alcohol", "caffeine")] or evs
        if not evs:
            return f"Nothing logged {win}."
        parts = []
        for e in evs[:12]:
            extra = f" ({e['carbs_g']} g carbs)" if e["carbs_g"] else f" ({e['insulin_units']} U)" if e["insulin_units"] else f" ({e['duration_min']} min)" if e["type"] == "exercise" else ""
            parts.append(f"{e['label']}{extra} at {e['time_text']}")
        t = r["totals"]
        tot = {"events": f"{t['carbs_g']} g of carbs over {t['meals']} meal{'s' if t['meals'] != 1 else ''}", "carbs": f"{t['carbs_g']} g of carbs",
               "insulin": f"{t['bolus_units']} U of meal insulin", "exercise": f"{t['exercise_min']} minutes of exercise",
               "caffeine": f"{t['caffeine_mg']} mg of caffeine", "alcohol": f"{t['drinks']} drinks ({t['alcohol_g']} g of alcohol)"}[m]
        return f"Logged {win}: " + "; ".join(parts) + f". In total {tot}."
    s = f"{win.capitalize()}: average {r['average']} mg/dL, {r['time_in_range_pct']}% in range, {r['n_lows']} lows"
    if r.get("min"):
        s += f", lowest {r['min']['value']} at {r['min']['time_text']}, highest {r['max']['value']} at {r['max']['time_text']}"
    return s + "."


def permission(r: Dict[str, Any]) -> str:
    return f"{r['plain']['headline']}. {r['plain']['reason']}"


def logged(r: Dict[str, Any]) -> str:
    st = r["state"]
    s = f"{r['understood']}. Your glucose is {st['glucose']} mg/dL and {st['trend']}; the model now has {st['carbs_digesting_g']} g of carbs digesting"
    if st.get("caffeine_mg"):
        s += f" and {st['caffeine_mg']} mg of caffeine in your body"
    return s + "."


def plan(r: Dict[str, Any]) -> str:
    return f"{r['plain']['headline']}. {r['plain']['reason']}"


def change(r: Dict[str, Any]) -> str:
    if r.get("error"):
        return f"{r['error']}. Options: {', '.join(r['options'])}."
    return f"{r['plain']['headline']}. {r['plain']['reason']}"


def compare(r: Dict[str, Any]) -> str:
    if r.get("error"):
        return r["error"]
    s = f"For {r['event']}, with your own settings: {r['personal']['headline']} ({r['personal']['p_low_pct']}% chance of a low). "
    s += f"For an average person with T1D: {r['population']['headline']} ({r['population']['p_low_pct']}%)."
    s += " Same answer, different numbers." if r["same_verdict"] else " Knowing you changes the answer."
    return s


def whatif(r: Dict[str, Any]) -> str:
    b, s, d = r["baseline"], r["scenario"], r["difference"]
    if r.get("nothing_changed"):
        return f"Nothing to change: there is no usual {r.get('skip') or 'event'} left before {r['to_text']} (the ones today are already logged)."
    what = ("skipping " + ", ".join(s["removed"])) if s["removed"] else ("adding " + ", ".join(s["added"]))
    out = f"By {r['to_text']}, {what} puts you at about {s['expected_at_end']} instead of {b['expected_at_end']} mg/dL."
    if s["low"]["time"] == r["times"][0] and b["low"]["time"] == r["times"][0]:
        out += " Neither path goes below where you are now"
    else:
        out += f" The low point becomes {s['low']['value']} around {s['low']['time_text']} (vs {b['low']['value']} as usual)"
    out += f" and the chance of a low goes from {b['p_low_pct']}% to {s['p_low_pct']}%."
    if abs(d["peak_delta"]) >= 8:
        out += f" The peak moves from {b['peak']['value']} to {s['peak']['value']}."
    return out


GENERAL = {
    "hypo": "A hypo (hypoglycaemia) is blood glucose under 70 mg/dL. Symptoms are shakiness, sweating, hunger and confusion; below 54 it is severe. The usual treatment is 15 g of fast carbs, then re-check after 15 minutes.",
    "hyper": "Hyperglycaemia is glucose above the target range (over 180 mg/dL; over 250 is where ketones become a concern). It comes from too little insulin for the carbs eaten, illness, stress or missed doses.",
    "ketone": "Ketones are made when the body burns fat instead of sugar. Small amounts are normal; above 0.6 mmol/L together with high glucose means not enough insulin is on board, and above 1.5 needs attention.",
    "insulin on board": "Insulin on board (IOB) is the rapid-acting insulin from recent doses that is still working. It peaks about 1-2 hours after a dose and lasts 3-5 hours.",
    "time in range": "Time in range is the share of sensor readings between 70 and 180 mg/dL. The common target is above 70 % of the time, with under 4 % below 70.",
    "carb ratio": "The carb ratio is how many grams of carbohydrate one unit of rapid-acting insulin covers, e.g. 1 unit per 10 g.",
    "basal": "Basal insulin is the slow background insulin that covers the liver's sugar release between meals and overnight; a bolus is the rapid dose taken for a meal or a correction.",
    "bolus": "A bolus is a dose of rapid-acting insulin taken for a meal or to correct a high; basal insulin is the slow background dose.",
    "hba1c": "HbA1c reflects average glucose over the last 2-3 months. An estimated A1c of 7 % corresponds to an average of about 154 mg/dL.",
    "dawn": "The dawn phenomenon is a rise in glucose in the early morning driven by hormones (cortisol, growth hormone) that make the liver release sugar and insulin work less well.",
}


def general(text: str) -> Optional[str]:
    t = text.lower()
    for k, v in GENERAL.items():
        if k in t or (k == "hypo" and ("low blood sugar" in t or "hypoglyc" in t)) or (k == "hyper" and "high blood sugar" in t):
            return v + " (This is general information, not from your data.)"
    return None


PHRASERS = {"get_current_state": state, "get_forecast": forecast, "explain_now": explain, "query_history": history,
            "evaluate_action": permission, "log_event": logged, "plan_day": plan, "change_lifestyle": change,
            "compare_to_average": compare, "whatif": whatif}


def for_tool(name: str, result: Dict[str, Any], question: str = "", focus: Optional[str] = None) -> str:
    if result.get("error") and name not in ("change_lifestyle", "compare_to_average"):
        return str(result["error"])
    fn = PHRASERS[name]
    if name in ("get_current_state", "explain_now"):
        return fn(result, focus)
    if name == "query_history":
        return fn(result, question)
    return fn(result)
