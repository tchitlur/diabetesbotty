import pytest
from fastapi.testclient import TestClient

from backend.config import DEMO_PATIENT_DIR
from backend.api.app import app


@pytest.fixture(scope="module")
def client():
    assert (DEMO_PATIENT_DIR / "fit.json").exists(), "run: python -m backend.inference.fitter --patient demo"
    with TestClient(app) as c:
        c.post("/profiles/demo/select")   # the active profile is a server-side file; another session may have left a different one
        c.post("/demo/reset")
        yield c


def test_health_state_forecast(client):
    assert client.get("/health").json()["ok"]
    st = client.get("/state").json()
    assert 30 < st["values"]["glucose"] < 400 and st["std"]["glucose"] > 0
    fc = client.get("/forecast").json()
    assert len(fc["times"]) == 97 and fc["p_hypo_8h"] > 0.0
    assert all(a <= b for a, b in zip(fc["p10"], fc["p90"]))


def test_parse_and_permission_flow(client):
    pe = client.post("/parse", json={"text": "can I have two more beers tonight"}).json()
    assert pe["event"]["type"] == "alcohol" and abs(pe["event"]["alcohol_g"] - 28) < 1
    card = client.post("/permission", json={"event": pe["event"]}).json()
    assert card["verdict"] in ("approved", "approved_with_condition", "denied")
    assert card["mini_curve"] and len(card["factors"]) <= 3 and card["data_used"]
    if card["verdict"] != "denied":
        client.post("/events/accept", json={"event": card["best_variant"]})
    pe2 = client.post("/parse", json={"text": "fasted run tomorrow at 7 for 30 min"}).json()
    assert pe2["event"]["type"] == "exercise" and pe2["event"]["start_time"].endswith("T07:00") and pe2["event"]["duration_min"] == 30
    card2 = client.post("/permission", json={"event": pe2["event"]}).json()
    assert card2["verdict"] in ("approved", "approved_with_condition", "denied")
    assert len(client.get("/cards").json()) >= 2


def test_stale_query_param_requests_data(client):
    pe = client.post("/parse", json={"text": "large coffee now"}).json()
    assert pe["event"]["type"] == "caffeine" and pe["event"]["caffeine_mg"] >= 60   # local table: 190; Gemini may say 95-190
    card = client.post("/permission?stale=30", json={"event": pe["event"]}).json()
    assert card["verdict"] == "request_data"
    assert "CGM" in card["condition"] or "CGM" in card["data_missing"][0]


def test_change_budget_alerts_plan(client):
    ch = client.post("/change", json={"name": "morning_workouts"}).json()
    assert ch["verdict"] in ("merged", "merged_with_changes", "rejected") and len(ch["diff"]) == 22
    assert set(ch["organ_risk_change"]) == {"dmg_eye", "dmg_kidney", "dmg_nerve", "dmg_cardio", "dmg_liver"}
    b = client.get("/budget").json()
    assert b["alcohol_g_per_week"] >= 0 and b["caffeine_mg_per_week"] >= 0 and b["off_plan_meals_per_week"] >= 0
    al = client.get("/alerts").json()
    assert isinstance(al, list)
    pl = client.get("/plan?date=tomorrow").json()
    assert len(pl["timeline"]) == 24 and pl["workout_start"]


def test_replay_alcohol_slider(client):
    days = client.get("/replay/days").json()
    fri = [d for d in days if d["weekday"] == "Fri" and d["drinks"] > 0]
    assert fri
    r1 = client.post("/replay", json={"date": fri[-1]["date"]}).json()
    r0 = client.post("/replay", json={"date": fri[-1]["date"], "alcohol_scale": 0.0}).json()
    assert len(r1["times"]) == len(r1["simulated"]) == len(r1["actual"])
    assert r0["min_glucose_modified"] >= r1["min_glucose_original"] - 1


def test_profiles_home_timeline(client):
    profs = client.get("/profiles").json()
    assert any(p["id"] == "demo" for p in profs) and client.get("/profiles/active").json()["id"] == "demo"
    h = client.get("/home").json()
    assert h["glucose"]["word"] in ("rising", "steady", "falling") and len(h["forecast"]["times"]) == 37
    keys = [t["key"] for t in h["tiles"]]
    assert {"carbs", "liver", "ketones", "energy", "recovery", "insulin"} <= set(keys) and not {"hydration", "body"} & set(keys)
    assert all(t["status"] and t["tone"] in ("good", "warn", "bad") and len(t["forecast"]["values"]) == 37 for t in h["tiles"])
    assert [c["key"] for c in h["coming_up"]] == ["meal", "workout", "risk", "best"]
    hist = h["history"]
    assert len(hist["times"]) == len(hist["raw"]) == len(hist["display"]) == 36
    assert sum(v is None for v in hist["display"]) <= sum(v is None for v in hist["raw"])   # display only fills short gaps
    tl = client.post("/plan/timeline", json={"workout": {"start": h["forecast"]["times"][-1], "duration_min": 30}}).json()
    assert tl["headline"] and tl["start"] < tl["now"] < tl["end"]
    assert tl["glucose_band"] and all(b["color"] in ("green", "amber", "red", "none") for b in tl["glucose_band"])
    assert all(b["reason"] for b in tl["exercise_band"])
    assert any(i["state"] == "suggested" and i["kind"] == "workout" and i["event"] for i in tl["items"])
    assert len(tl["sparkline"]["times"]) == len(tl["sparkline"]["values"]) == len(tl["sparkline"]["kind"])
    card = client.get("/why").json()
    assert "plain" in card and card["plain"]["headline"]


def test_drift_clinician_why(client):
    d = client.get("/drift").json()
    assert "score" in d and "flagged" in d
    c = client.get("/clinician").json()
    assert c["fitted_params"] and isinstance(c["residual_log"], list)
    assert "verdict" in client.get("/why").json()


def test_five_people_in_order_and_parser_toggle(client):
    profs = client.get("/profiles").json()
    names = [p["name"] for p in profs][:5]
    assert names == ["Alex", "Priya", "Ken", "Marcus", "Zara"]
    by = {p["name"]: p for p in profs}
    assert by["Ken"]["occupation"] == "Line cook" and by["Marcus"]["occupation"] == "Nurse" and by["Zara"]["occupation"] == "Barista"
    assert len({p["avatar"] for p in profs[:5]}) == 5 and all(p["signature"] for p in profs[:5])
    assert by["Ken"]["target_high"] == 160 and by["Alex"]["carb_ratio_g_per_u"] == 37 and by["Priya"]["carb_ratio_g_per_u"] == 17
    assert client.delete("/profiles/zara").status_code == 400   # the five cannot be deleted
    st = client.post("/parser/mode", json={"ai_reader": False}).json()
    assert st["ai_reader"] is False and st["gemini_configured"] is False
    st = client.post("/parser/mode", json={"ai_reader": True}).json()
    assert st["ai_reader"] is True
