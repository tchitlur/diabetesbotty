"""Safety gate: runs before any decision. Returns proceed | request_data(what)
| escalate(reason). Rules and thresholds come from rules.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml

from backend.config import RULES_PATH


@lru_cache(maxsize=1)
def load_rules() -> Dict[str, Any]:
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class GateContext:
    glucose: float
    ketones: float
    staleness_min: float
    data_quality: float
    readings_below_54_24h: int = 0
    drift_flagged_days: int = 0
    proposed_type: Optional[str] = None


@dataclass
class GateDecision:
    action: str                     # proceed | request_data | escalate
    reason: str = ""
    what: str = ""                  # for request_data: what is needed
    instruction: str = ""           # for escalate
    rule: str = ""
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "reason": self.reason, "what": self.what, "instruction": self.instruction,
                "rule": self.rule, "checks": self.checks}


def run_gate(ctx: GateContext) -> GateDecision:
    r = load_rules()
    hard, esc, msg = r["hard_rules"], r["escalation"], r["messages"]
    checks: List[Dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"rule": name, "ok": bool(ok), "detail": detail})

    # ---- escalations first (they override everything)
    dka = ctx.ketones > esc["dka_ketones_mmol"] and ctx.glucose > esc["dka_glucose_mgdl"]
    check("dka", not dka, f"ketones {ctx.ketones:.2f} mmol/L, glucose {ctx.glucose:.0f} mg/dL")
    if dka:
        return GateDecision("escalate", "possible DKA", instruction=msg["escalate_dka"].format(ketones=ctx.ketones, glucose=ctx.glucose), rule="dka", checks=checks)
    hypos = ctx.readings_below_54_24h >= esc["severe_hypo_count_24h"]
    check("severe_hypos_24h", not hypos, f"{ctx.readings_below_54_24h} readings < 54 mg/dL in 24 h")
    if hypos:
        return GateDecision("escalate", "repeated severe hypoglycaemia", instruction=msg["escalate_hypos"].format(count=ctx.readings_below_54_24h), rule="severe_hypos_24h", checks=checks)
    drift = ctx.drift_flagged_days >= esc["drift_flagged_days"]
    check("drift", not drift, f"drift flagged for {ctx.drift_flagged_days} days")
    if drift:
        return GateDecision("escalate", "model drift", instruction=msg["escalate_drift"].format(days=ctx.drift_flagged_days), rule="drift", checks=checks)

    # ---- data requests
    stale = ctx.staleness_min > hard["no_approval_if_staleness_min"]
    check("cgm_fresh", not stale, f"last CGM reading {ctx.staleness_min:.0f} min old (limit {hard['no_approval_if_staleness_min']})")
    if stale:
        return GateDecision("request_data", "CGM reading too old", what="fresh CGM reading", instruction=msg["request_cgm"].format(staleness=ctx.staleness_min), rule="cgm_fresh", checks=checks)
    low_q = ctx.data_quality < hard["min_data_quality_for_approval"]
    check("data_quality", not low_q, f"data quality {ctx.data_quality:.2f} (min {hard['min_data_quality_for_approval']})")
    if low_q:
        return GateDecision("request_data", "data quality too low", what="24 h of clean CGM data", instruction=msg["request_quality"].format(quality=ctx.data_quality), rule="data_quality", checks=checks)

    # ---- event-type rules (these deny rather than block; the decision layer turns them into conditions)
    if ctx.proposed_type == "exercise":
        ok = ctx.glucose >= hard["no_exercise_below_glucose_mgdl"]
        check("exercise_glucose_floor", ok, f"glucose {ctx.glucose:.0f} (floor {hard['no_exercise_below_glucose_mgdl']})")
        if not ok:
            return GateDecision("proceed", "exercise below glucose floor", instruction=msg["exercise_low"].format(glucose=ctx.glucose), rule="exercise_glucose_floor", checks=checks)
    if ctx.proposed_type == "alcohol":
        ok = ctx.ketones <= hard["no_alcohol_above_ketones_mmol"]
        check("alcohol_ketone_ceiling", ok, f"ketones {ctx.ketones:.2f} (ceiling {hard['no_alcohol_above_ketones_mmol']})")
        if not ok:
            return GateDecision("proceed", "ketones too high for alcohol", instruction=msg["alcohol_ketones"].format(ketones=ctx.ketones), rule="alcohol_ketone_ceiling", checks=checks)
    return GateDecision("proceed", "all checks passed", checks=checks)
