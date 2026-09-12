"""The 24 reference messages through the full chat path. With the local router (always): the
expected tool is chosen and the answer carries a number that came from the tool result. With a
Gemini key (skipped otherwise): the same 24 are logged to audit/chat_transcript.md and must
produce zero grounding violations."""
import os
os.environ["GLUCOPILOT_LIVE_CLOCK"] = "0"

import re
from pathlib import Path

import pytest

from backend.api.twin import Twin
from backend.chat.router import handle, check_grounding, classify_local
from backend.chat import tools as T
from backend.config import gemini_available

# message -> (expected tool or None, card type, must the answer contain a number)
CASES = [
    ("what is my current glucose", "get_current_state", "state", True),
    ("what's my glucose", "get_current_state", "state", True),
    ("am I going up or down", "get_current_state", "state", True),
    ("what will my glucose be in 2 hours", "get_forecast", "forecast", True),
    ("will I go low tonight", "get_forecast", "forecast", True),
    ("I ate 15 minutes ago, why is my glucose not rising", "explain_now", "explain", True),
    ("why am I dropping", "explain_now", "explain", True),
    ("how much insulin is still active", "explain_now", "explain", True),
    ("how many carbs are still digesting", "explain_now", "explain", True),
    ("what was my glucose at 3pm", "query_history", "history", True),
    ("how many lows did I have this week", "query_history", "history", True),
    ("what's my average this week", "query_history", "history", True),
    ("what did I eat yesterday", "query_history", "history", True),
    ("when was my last low", "query_history", "history", True),
    ("I just ate a bagel", "log_event", "logged", True),
    ("I had a large coffee 20 minutes ago", "log_event", "logged", True),
    ("just finished a 30 minute run", "log_event", "logged", True),
    ("can I have pizza for dinner", "evaluate_action", "permission", True),
    ("run at 7 tomorrow for 30 min", "evaluate_action", "permission", True),
    ("what if I skip dinner", "whatif", "forecast", False),
    ("what if I have two coffees", "whatif", "forecast", True),
    ("/plan tomorrow", "plan_day", "plan", True),
    ("what is a hypo", None, "text", False),
    ("how much sleep did I get last night", "query_history", "history", True),
]
NUM = re.compile(r"\d")


@pytest.fixture(scope="module")
def twin():
    return Twin("demo")


@pytest.fixture(scope="module")
def local_runs(twin):
    return [(m, handle(twin, m, use_gemini=False)) for m, _, _, _ in CASES]


def test_local_routing_and_grounding(local_runs):
    for (m, tool, card, needs_num), (_, r) in zip(CASES, local_runs):
        assert r["router"] == "local"
        if tool is None:
            assert r["tools"] == [] and r["card"]["type"] == "text", m
            assert r["grounding"]["general"], m
        else:
            assert r["tools"] == [tool], (m, r["tools"])
            assert r["card"]["type"] == card, (m, r["card"]["type"])
            assert r["card"]["payload"], m
        assert r["answer"] and "NaN" not in r["answer"] and "None" not in r["answer"], (m, r["answer"])
        assert not r["grounding"]["violations"], (m, r["grounding"])
        if needs_num:
            assert NUM.search(r["answer"]), (m, r["answer"])


def test_explain_card_after_eating(twin):
    r = handle(twin, "I ate 15 minutes ago, why is my glucose not rising", use_gemini=False)
    assert r["card"]["type"] == "explain"
    p = r["card"]["payload"]["pending"]
    assert p["carbs_g"] > 0
    assert p["carbs_peak_in_min"] is not None or p["carbs_done_in_min"] is not None
    assert re.search(r"digest|absorb", r["answer"]) and re.search(r"\d+ min", r["answer"]), r["answer"]
    terms = {t["key"]: t["mgdl_per_hour"] for t in r["card"]["payload"]["terms"]}
    assert terms["carbs"] > 0 and terms["insulin"] < 0
    assert abs(sum(terms.values()) - r["card"]["payload"]["model_rate_mgdl_per_hour"]) < 0.5


def test_log_changes_state(twin):
    before = T.get_current_state(twin)["caffeine_mg"]
    r = handle(twin, "I had a large coffee 20 minutes ago", use_gemini=False)
    assert r["card"]["type"] == "logged"
    ev = r["card"]["payload"]["event"]
    assert ev["type"] == "caffeine" and ev["caffeine_mg"] == 190 and ev["start_time"].endswith("18:40")
    assert r["card"]["payload"]["state"]["caffeine_mg"] > before
    assert any(e.source == "chat" for e in twin.pt.events)


def test_grounding_check_catches_invented_numbers():
    results = [("get_current_state", {}, {"glucose": 132, "trend": "steady", "as_of": "2025-08-29T19:00", "p_low": 0.08})]
    assert check_grounding("Your glucose is 132 mg/dL as of 7:00 pm; a low is 8% likely.", results, "what's my glucose") == []
    bad = check_grounding("Your glucose is 145 mg/dL at 7:30 pm.", results, "what's my glucose")
    assert "145" in bad and "7:30 pm" in bad


def test_history_windows(twin):
    name, args, _, _ = classify_local("what was my glucose at 3pm", twin)
    assert name == "query_history" and args["start"].endswith("T15:00") and args["metric"] == "glucose"
    name, args, _, _ = classify_local("what did I eat yesterday", twin)
    assert args["metric"] == "events" and args["start"].endswith("T00:00")
    name, args, _, _ = classify_local("how much sleep did I get last night", twin)
    assert args["metric"] == "sleep"


@pytest.mark.skipif(not gemini_available(), reason="no GEMINI_API_KEY")
def test_gemini_transcript_has_no_grounding_violations():
    from backend.chat.transcript import run
    out = Path(__file__).resolve().parents[2] / "audit" / "chat_transcript.md"
    violations = run(True, out)
    assert out.exists()
    assert violations == 0
