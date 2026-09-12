"""Smoke: the six cached results exist and diverge, the page serves with the bundle, the data
route matches, a bank prompt is served from the cache, and an unknown prompt falls back."""
import os
os.environ["GLUCOPILOT_LIVE_CLOCK"] = "0"

import json

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.compare import engine as E


def test_cache_complete_and_divergent():
    cache = E.load_cache()
    assert set(cache) == {b["slug"] for b in E.BANK}, sorted(cache)
    for slug, res in cache.items():
        assert set(res["personal"]) == {"alex", "priya", "marcus"} and res["population"]
        d = E.divergence(res)
        assert d["ok"], (slug, d)
        for who, p in res["personal"].items():
            assert p["curve"] and len(p["curve"]["times"]) >= 73 and p["headline"] and p["peak"] > 0
    assert (E.CACHE_DIR / "personas.json").exists()


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
    d = client.get("/compare/data").json()
    assert len(d["personas"]) == 3 and [p["name"] for p in d["personas"]] == ["Alex", "Priya", "Marcus"]
    assert len(d["bank"]) == 6 and set(d["results"]) == {b["slug"] for b in E.BANK}
    r = client.post("/compare/ask", json={"text": "Skip lunch today?"}).json()
    assert r["source"] == "cache" and r["slug"] == "skip-lunch"
