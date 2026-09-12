"""Build the frozen /compare cache: run the six bank prompts for Alex, Priya and Marcus (and the
population model) at COMPARE_NOW (live clock off), check the divergence rule (three different
verdicts and three different causes on every prompt), write backend/data/compare_cache/*.json,
personas.json and audit/compare_divergence.md.
Usage: python -m backend.compare.build [--check]"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("GLUCOPILOT_LIVE_CLOCK", "0")

from backend.compare import engine as E   # noqa: E402

PARAM_KEYS = ["carb_ratio", "tau_carb", "si_tod0", "si_tod1", "si_tod2", "sleep_debt_coef", "exercise_mult"]
PARAM_LABEL = {"carb_ratio": "carb bioavailability", "tau_carb": "absorption time constant (min)", "si_tod0": "insulin sensitivity, night",
               "si_tod1": "insulin sensitivity, day", "si_tod2": "insulin sensitivity, evening", "sleep_debt_coef": "sleep-debt effect", "exercise_mult": "exercise effect"}
CLASS_WORD = {"go": "Go ahead", "condition": "Yes, with a condition", "wait": "Better to wait"}


def main(check_only: bool = False) -> int:
    t0 = time.time()
    twins = E.get_twins()
    now = E.twins_now()
    dash = {pid: E.persona_dashboard(tw) for pid, tw in twins.items()}
    results = {}
    for b in E.BANK:
        t1 = time.time()
        item = E.resolve_item(b, now)
        res = E.run_all(item, dashboards=dash)
        results[b["slug"]] = res
        d = res["divergence"]
        print(f"{b['slug']:<11} {d['classes']} causes={d['causes']} peaks={d['peaks']} ok={d['ok']} ({time.time() - t1:.0f} s)")
    ok_all = all(r["divergence"]["ok"] for r in results.values())
    if not check_only:
        E.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for slug, res in results.items():
            E.cache_path(slug).write_text(json.dumps(res, indent=1), encoding="utf-8")
        stats = [dash[pid] for pid in E.PERSONA_IDS]
        (E.CACHE_DIR / "personas.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
        write_report(twins, results, stats, now)
    print(f"three distinct verdicts and causes on all six: {ok_all} ({time.time() - t0:.0f} s)")
    return 0 if ok_all else 1


def write_report(twins, results, stats, now) -> None:
    over = E.load_overrides()
    names = {"demo": "alex", "priya": "priya", "marcus": "marcus"}
    lines = ["# /compare: verdict matrix, parameters and divergence", "",
             f"Frozen build at {now.isoformat(timespec='minutes')} (the live page runs the same code at the wall clock). "
             "Population model: priors, glucose 120 at steady state, no history.", "",
             "## Verdict matrix (6 prompts x 3 people)", "",
             "Rule: on every prompt the three verdicts are three different classes (go ahead / yes, with a condition / better to wait) "
             "and the three reasons name three different causes.", "",
             "| prompt | Alex | Priya | Marcus | ok |", "|---|---|---|---|---|"]
    for slug, res in results.items():
        cells = []
        for who in E.ORDER:
            p = res["personal"][who]
            cells.append(f"**{p['headline']}** ({p['cause']['key']}: {p['cause']['text']})")
        lines.append(f"| {res['text']} | " + " | ".join(cells) + f" | {'ok' if res['divergence']['ok'] else 'NOT OK'} |")
    lines += ["", "## Fitted parameters (after tuning, if any)", "", "| parameter | Alex | Priya | Marcus | prior |", "|---|---|---|---|---|"]
    for k in PARAM_KEYS:
        row = [f"{twins[pid].params.get(k, 0):.3f}" + (" *" if over.get(pid, {}).get(k) is not None else "") for pid in E.PERSONA_IDS]
        prior = next((twins[pid].pt.fit["params"][k]["prior"] for pid in E.PERSONA_IDS if twins[pid].pt.fit and k in twins[pid].pt.fit["params"]), None)
        lines.append(f"| {PARAM_LABEL[k]} (`{k}`) | {' | '.join(row)} | {prior if prior is None else f'{prior:.3f}'} |")
    lines += ["", "`*` = tuned for the demo (backend/data/compare_personas.json), within the plausible ranges." if over else "No parameters were tuned: the fitted values diverge on their own.", "",
              "## Starting point", "", "| | Alex | Priya | Marcus |", "|---|---|---|---|"]
    for key, label in [("glucose", "glucose now"), ("trend", "trend"), ("tir7", "time in range, 7 d (%)"), ("avg7", "average, 7 d"), ("lows7", "lows, 7 d (episodes of 15+ min)"), ("carb_ratio_text", "carb ratio"), ("insulin_working", "insulin working (%)"), ("recovery", "recovery")]:
        lines.append(f"| {label} | " + " | ".join(str(s[key]) for s in stats) + " |")
    lines.append("| amber / red tiles | " + " | ".join(", ".join(t["key"] for t in s["tiles"] if t["tone"] != "good") or "none" for s in stats) + " |")
    lines.append("| next meal | " + " | ".join(next((c["time"] or "-" for c in s["coming_up"] if c["key"] == "meal"), "-") for s in stats) + " |")
    lines.append("| learned chips | " + " | ".join("; ".join(f"{c['icon']} {c['label']}" for c in s["chips"]) for s in stats) + " |")
    lines += ["", "## The six prompts in detail", "", "| prompt | person | verdict | cause | peak | at | low | P(low) | condition |", "|---|---|---|---|---|---|---|---|---|"]
    for slug, res in results.items():
        for who in E.ORDER:
            p = res["personal"][who]
            lines.append(f"| {res['text']} | {who.capitalize()} | {p['headline']} | {p['cause']['key']} | {p['peak']} | {p['peak_time_text']} | {p['low']} | {p['p_low_word']} ({p['p_low']:.2f}) | {p['condition'] or '-'} |")
        pop = res["population"]
        lines.append(f"| {res['text']} | average person | {pop['headline']} | - | {pop['peak']} | {pop['peak_time_text']} | {pop['low']} | {pop['p_low_word']} ({pop['p_low']:.2f}) | {pop['condition'] or '-'} |")
        d = res["divergence"]
        lines.append(f"| | *divergence* | {'3 classes' if d['criteria']['verdicts'] else 'same class twice'} | {'3 causes' if d['criteria']['causes'] else 'cause repeated'} | spread {d['peak_spread']} | spread {d['peak_time_spread_min']} min | | | **{'ok' if d['ok'] else 'NOT OK'}** |")
    out = Path(__file__).resolve().parents[2] / "audit" / "compare_divergence.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
