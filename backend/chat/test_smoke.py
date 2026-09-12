"""Smoke: every tool runs on the demo twin and returns JSON-serialisable output with the keys
the phrasers and the cards read."""
import os
os.environ["GLUCOPILOT_LIVE_CLOCK"] = "0"

import json

import pytest

from backend.api.twin import Twin
from backend.chat import tools as T
from backend.chat import phrase


@pytest.fixture(scope="module")
def twin():
    return Twin("demo")


def test_every_tool_has_a_schema_and_docstring():
    for name, spec in T.TOOLS.items():
        assert T.describe(name), name
        assert spec["parameters"]["type"] == "OBJECT"


def test_tools_run_and_phrase(twin):
    now = twin.now.isoformat(timespec="minutes")
    calls = [("get_current_state", {}), ("get_forecast", {"hours": 3}), ("explain_now", {}),
             ("query_history", {"start": now[:10] + "T00:00", "end": now, "metric": "glucose"}),
             ("whatif", {"events": [{"type": "caffeine", "caffeine_mg": 95, "label": "coffee"}]}),
             ("evaluate_action", {"event": {"type": "meal", "carbs_g": 30, "label": "toast"}})]
    for name, args in calls:
        r = T.call(twin, name, args)
        json.dumps(r)   # serialisable
        assert "error" not in r, (name, r.get("error"))
        s = phrase.for_tool(name, r)
        assert s and len(s) > 20, name
    fc = T.get_forecast(twin, 2)
    assert len(fc["times"]) == 25 and fc["p_low_pct"] >= 0
    ex = T.explain_now(twin)
    assert {t["key"] for t in ex["terms"]} >= {"carbs", "liver", "insulin", "basic"}
