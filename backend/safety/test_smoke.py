from backend.safety.gate import run_gate, GateContext, load_rules
from backend.safety.explain import confidence_score, data_inventory


def _ctx(**kw):
    base = dict(glucose=120, ketones=0.1, staleness_min=5, data_quality=0.8, readings_below_54_24h=0, drift_flagged_days=0, proposed_type=None)
    base.update(kw)
    return GateContext(**base)


def test_rules_load():
    r = load_rules()
    assert r["hard_rules"]["no_exercise_below_glucose_mgdl"] == 90
    assert r["escalation"]["severe_hypo_count_24h"] == 3


def test_gate_paths():
    assert run_gate(_ctx()).action == "proceed"
    assert run_gate(_ctx(staleness_min=30)).action == "request_data"
    assert run_gate(_ctx(data_quality=0.1)).action == "request_data"
    assert run_gate(_ctx(ketones=2.0, glucose=300)).action == "escalate"
    assert run_gate(_ctx(readings_below_54_24h=3)).action == "escalate"
    assert run_gate(_ctx(drift_flagged_days=5)).action == "escalate"
    d = run_gate(_ctx(glucose=80, proposed_type="exercise"))
    assert d.action == "proceed" and d.rule == "exercise_glucose_floor"
    d = run_gate(_ctx(ketones=0.9, proposed_type="alcohol"))
    assert d.rule == "alcohol_ketone_ceiling"


def test_explain_helpers():
    c = confidence_score(0.8, {"a": {"mean": 1.0, "std": 0.1}}, None, 5.0, 1.0)
    assert 0 < c <= 1
    inv = data_inventory(True, 5.0, True, True, {"meal": 3, "insulin": 3})
    assert inv["data_used"] and "last night's sleep" in inv["data_missing"]
