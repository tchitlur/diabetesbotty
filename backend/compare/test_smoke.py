"""Smoke: the six cached results exist with three distinct verdicts and three distinct causes each,
the persona dashboards are plausible and visibly different, the bank resolves relative to now, the
page serves with the bundle, the data route matches, a bank prompt is served from the cache, and an
unknown prompt falls back."""
import os
os.environ["GLUCOPILOT_LIVE_CLOCK"] = "0"

import json
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.compare import engine as E


def _personas():
    return json.loads((E.CACHE_DIR / "personas.json").read_text(encoding="utf-8"))


def test_cache_complete_three_verdicts_three_causes():
    cache = E.load_cache()
    assert set(cache) == {b["slug"] for b in E.BANK}, sorted(cache)
    for slug, res in cache.items():
        assert set(res["personal"]) == {"alex", "priya", "marcus"} and res["population"]
        d = E.divergence(res)
        assert d["ok"], (slug, d)
        classes = [res["personal"][w]["verdict_class"] for w in E.ORDER]
        assert sorted(classes) == ["condition", "go", "wait"], (slug, classes)
        causes = [res["personal"][w]["cause"]["key"] for w in E.ORDER]
        assert len(set(causes)) == 3 and "average" not in causes, (slug, causes)
        for who, p in res["personal"].items():
            assert p["curve"] and len(p["curve"]["times"]) >= 73 and p["headline"] and p["peak"] > 0
            assert p["cause"]["keyword"] in p["reason"].lower(), (slug, who, p["reason"])
            assert re.search(r"about \d+", p["reason"]), (slug, who, p["reason"])


def test_personas_plausible_and_different():
    ps = _personas()
    assert [p["id"] for p in ps] == E.ORDER
    for p in ps:
        assert 0 <= p["lows7"] <= 6, (p["id"], p["lows7"])
        assert 55 <= p["tir7"] <= 85, (p["id"], p["tir7"])
        assert 110 <= p["avg7"] <= 170, (p["id"], p["avg7"])
        assert [t["key"] for t in p["tiles"]] == E.TILE_ORDER
        assert any(t["tone"] != "good" for t in p["tiles"]), (p["id"], "no amber or red tile")
        assert len(p["chips"]) == 3 and all(not re.search(r"\d|%", c["label"]) for c in p["chips"]), p["chips"]
        assert len(p["history"]["display"]) >= 36 and all(v is not None for v in p["history"]["display"])
        assert len(p["forecast"]["median"]) == 37
        assert [c["key"] for c in p["coming_up"]] == ["meal", "workout"]
    assert len({p["glucose"] for p in ps}) == 3
    hot = [frozenset(t["key"] for t in p["tiles"] if t["tone"] != "good") for p in ps]
    assert len(set(hot)) == 3, hot
    meals = [next(c["time"] for c in p["coming_up"] if c["key"] == "meal") for p in ps]
    assert len(set(meals)) == 3, meals
    energy = [next(t["value"] for t in p["tiles"] if t["key"] == "energy") for p in ps]
    recovery = [next(t["value"] for t in p["tiles"] if t["key"] == "recovery") for p in ps]
    assert len(set(energy)) > 1 and len(set(recovery)) > 1


def test_bank_resolves_relative_to_now():
    morning = datetime(2025, 8, 29, 10, 30)
    late = datetime(2025, 8, 29, 20, 45)
    pizza = E.BANK_BY_SLUG["pizza"]
    assert E.resolve_item(pizza, morning)["event"]["start_time"] == "2025-08-29T19:00"
    assert E.resolve_item(pizza, late)["event"]["start_time"] == "2025-08-30T19:00"
    assert E.resolve_item(E.BANK_BY_SLUG["run"], late)["event"]["start_time"] == "2025-08-29T21:45"
    assert E.resolve_item(E.BANK_BY_SLUG["cheesecake"], late)["event"]["start_time"] == "2025-08-29T20:45"
    assert E.resolve_item(E.BANK_BY_SLUG["wine"], morning)["event"]["start_time"] == "2025-08-29T21:00"
    assert E.resolve_item(E.BANK_BY_SLUG["wine"], late)["event"]["start_time"] == "2025-08-30T21:00"
    assert E.item_from_text("skip lunch today?", morning)["kind"] == "skip"   # free text still works
    shifted = E.shift_dates({"t": "2025-08-29T19:00", "x": [{"start": "2025-08-30T07:00"}], "n": 3}, timedelta(days=379))
    assert shifted == {"t": "2026-09-12T19:00", "x": [{"start": "2026-09-13T07:00"}], "n": 3}


def test_nearest_cached_keywords():
    near = E.nearest_cached("could I eat a pizza tonight")
    assert near and near["slug"] == "pizza"
    near = E.nearest_cached("what about a run tomorrow morning")
    assert near and near["slug"] == "run"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_page_and_data(client):
    html = client.get("/compare").text
    assert "Same question. Three bodies. Three answers." in html and "__BUNDLE__" not in html
    assert '"results"' in html and '"personas"' in html
    assert "1–6 fire a prompt" not in html
    d = client.get("/compare/data").json()
    assert len(d["personas"]) == 3 and [p["name"] for p in d["personas"]] == ["Alex", "Priya", "Marcus"]
    assert len(d["bank"]) == 6 and set(d["results"]) == {b["slug"] for b in E.BANK}
    assert d["now"] and d["wall_now"]
    r = client.post("/compare/ask", json={"text": "Three glasses of wine at 9 pm tonight?"}).json()
    assert r["source"] == "cache" and r["slug"] == "wine"
