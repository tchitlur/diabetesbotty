"""Build the /compare cache: run the six bank prompts for Alex, Priya and Marcus (and the
population model), check the divergence rule, write backend/data/compare_cache/*.json,
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


def main(check_only: bool = False) -> int:
    t0 = time.time()
    twins = E.get_twins()
    results = {}
    for item in E.BANK:
        t1 = time.time()
        res = E.run_all(item)
        results[item["slug"]] = res
        d = res["divergence"]
        print(f"{item['slug']:<11} verdicts={d['verdicts']} peaks={d['peaks']} spread={d['peak_spread']} time_spread={d['peak_time_spread_min']} ok={d['ok']} ({time.time() - t1:.0f} s)")
    ok_all = all(r["divergence"]["ok"] for r in results.values())
    if not check_only:
        E.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for slug, res in results.items():
            E.cache_path(slug).write_text(json.dumps(res, indent=1), encoding="utf-8")
        stats = E.persona_stats()
        (E.CACHE_DIR / "personas.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
        write_report(twins, results, stats)
    print(f"divergence ok for all six: {ok_all} ({time.time() - t0:.0f} s)")
    return 0 if ok_all else 1


def write_report(twins, results, stats) -> None:
    over = E.load_overrides()
    lines = ["# /compare: parameters and divergence", "", f"Frozen at {E.COMPARE_NOW.isoformat(timespec='minutes')} (Friday). Population model: priors, glucose 120 at steady state, no history.", "",
             "## Fitted parameters (after tuning, if any)", "", "| parameter | Alex | Priya | Marcus | prior |", "|---|---|---|---|---|"]
    names = {"demo": "alex", "priya": "priya", "marcus": "marcus"}
    for k in PARAM_KEYS:
        row = [f"{twins[pid].params.get(k, 0):.3f}" + (" *" if over.get(names[pid], {}).get(k) is not None else "") for pid in E.PERSONA_IDS]
        prior = next((twins[pid].pt.fit["params"][k]["prior"] for pid in E.PERSONA_IDS if twins[pid].pt.fit and k in twins[pid].pt.fit["params"]), None)
        lines.append(f"| {PARAM_LABEL[k]} (`{k}`) | {' | '.join(row)} | {prior if prior is None else f'{prior:.3f}'} |")
    lines += ["", "`*` = tuned for the demo (backend/data/compare_personas.json), within the plausible ranges." if over else "No parameters were tuned: the fitted values diverge on their own.", "",
              "## Starting point", "", "| | Alex | Priya | Marcus |", "|---|---|---|---|"]
    for key, label in [("glucose", "glucose now"), ("tir7", "time in range, 7 d (%)"), ("avg7", "average, 7 d"), ("lows7", "lows, 7 d"), ("carb_ratio_text", "carb ratio"), ("insulin_working", "insulin working (%)"), ("recovery", "recovery")]:
        lines.append(f"| {label} | " + " | ".join(str(s[key]) for s in stats) + " |")
    lines += ["", "## The six prompts", "", "| prompt | person | verdict | peak | at | low | P(low) | condition |", "|---|---|---|---|---|---|---|---|"]
    for slug, res in results.items():
        for who in ("alex", "priya", "marcus"):
            p = res["personal"][who]
            lines.append(f"| {res['text']} | {who.capitalize()} | {p['headline']} | {p['peak']} | {p['peak_time_text']} | {p['low']} | {p['p_low_word']} ({p['p_low']:.2f}) | {p['condition'] or '-'} |")
        pop = res["population"]
        lines.append(f"| {res['text']} | average person | {pop['headline']} | {pop['peak']} | {pop['peak_time_text']} | {pop['low']} | {pop['p_low_word']} ({pop['p_low']:.2f}) | {pop['condition'] or '-'} |")
        d = res["divergence"]
        lines.append(f"| | *divergence* | {'differ' if d['criteria']['verdict'] else 'same'} | spread {d['peak_spread']} | spread {d['peak_time_spread_min']} min | | | **{'ok' if d['ok'] else 'NOT OK'}** ({sum(d['criteria'].values())}/3) |")
    out = Path(__file__).resolve().parents[2] / "audit" / "compare_divergence.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
