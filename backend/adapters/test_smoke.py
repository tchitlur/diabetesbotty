import numpy as np
import pandas as pd

from backend.adapters.csv_ingest import ingest_csv, write_dexcom_csv, write_libre_csv, validate_series


def _series(n=300, start="2025-06-01T00:00"):
    t = pd.date_range(start, periods=n, freq="5min")
    g = 120 + 30 * np.sin(np.arange(n) / 20.0)
    return t, g


def test_dexcom_roundtrip(tmp_path):
    t, g = _series()
    g[50:55] = np.nan            # dropout
    g[100] = g[99] + 40          # artifact (8 mg/dL/min)
    p = tmp_path / "dex.csv"
    write_dexcom_csv(p, t, g)
    s = ingest_csv(p)
    assert s.source_format == "dexcom"
    assert len(s.times) >= 299
    assert any(gp["minutes"] >= 15 for gp in s.gaps)
    assert s.artifact.any()
    assert 0.0 <= s.data_quality <= 1.0
    assert s.staleness_min == 0.0


def test_libre_roundtrip(tmp_path):
    t, g = _series(n=100)
    p = tmp_path / "libre.csv"
    write_libre_csv(p, t, g)
    s = ingest_csv(p)
    assert s.source_format == "libre"
    assert np.nanmax(np.abs(s.glucose[s.valid] - np.round(g[s.valid]))) < 1.0


def test_staleness_lowers_quality():
    t, g = _series(n=288)
    raw = pd.DataFrame({"time": t, "glucose": g})
    fresh = validate_series(raw, now=t[-1].to_pydatetime())
    stale = validate_series(raw, now=(t[-1] + pd.Timedelta("45min")).to_pydatetime())
    assert stale.staleness_min == 45.0
    assert stale.data_quality < fresh.data_quality


# ---------------------------------------------------------------- parsers
import datetime as _dt
import json as _json

NOW = _dt.datetime.fromisoformat("2025-08-29T19:00")


def test_local_parser_required_examples():
    from backend.adapters.local_parser import parse_text_local
    e = parse_text_local("can I have two more beers tonight", NOW).event
    assert e.type == "alcohol" and abs(e.alcohol_g - 28) < 0.1 and e.carbs_g == 26 and e.start_time == "2025-08-29T19:00"
    e = parse_text_local("fasted run tomorrow at 7 for 30 min", NOW).event
    assert e.type == "exercise" and e.exercise_kind == "aerobic" and e.duration_min == 30 and e.start_time == "2025-08-30T07:00"
    e = parse_text_local("two shots of vodka at 11pm", NOW).event
    assert e.type == "alcohol" and abs(e.alcohol_g - 28) < 0.1 and e.start_time == "2025-08-29T23:00"
    e = parse_text_local("large coffee now", NOW).event
    assert e.type == "caffeine" and e.caffeine_mg == 190
    e = parse_text_local("can I lift for 45 min at 6pm", NOW).event
    assert e.type == "exercise" and e.exercise_kind == "anaerobic" and e.duration_min == 45 and e.start_time == "2025-08-30T18:00"


def test_gemini_json_extraction_and_validation():
    from backend.adapters.gemini_common import extract_json, to_event
    obj = extract_json('```json\n{"type": "alcohol", "alcohol_g": 28, "carbs_g": 26, "start_time": "2025-08-29T21:00", "label": "2 beers"}\n```')
    ev = to_event(obj, NOW)
    assert ev.type == "alcohol" and ev.alcohol_g == 28 and ev.source == "gemini"
    obj = extract_json('Sure! Here is the JSON: {"type": "exercise", "exercise_kind": "aerobic", "duration_min": 30}')
    assert to_event(obj, NOW).exercise_kind == "aerobic"
    import pytest
    with pytest.raises(ValueError):
        to_event({"type": "nap"}, NOW)


def test_gemini_text_with_mocked_model(monkeypatch):
    import backend.adapters.gemini_text as gt
    payload = {"type": "alcohol", "start_time": "2025-08-29T21:00", "duration_min": 90, "alcohol_g": 28, "carbs_g": 26,
               "label": "2 beers", "confidence": 0.9, "items": [{"name": "beer", "count": 2, "serving": "12 oz"}], "notes": "question"}
    monkeypatch.setattr(gt, "generate", lambda contents, **kw: "```json\n" + _json.dumps(payload) + "\n```")
    pe = gt.parse_text_gemini("can I have two more beers tonight", NOW)
    assert pe.parser == "gemini" and pe.event.type == "alcohol" and pe.confidence == 0.9
    assert pe.raw_items and "beer" in pe.raw_items[0]["item"]


def test_gemini_vision_cross_check(monkeypatch):
    import backend.adapters.gemini_vision as gv
    payload = {"items": [{"name": "pizza", "portion": "2 slices", "count": 2, "carbs_g": 10, "fat_g": 20, "protein_g": 24, "uncertainty": 0.3},
                         {"name": "kimchi tofu bowl", "portion": "1 bowl", "count": 1, "carbs_g": 33, "fat_g": 9, "protein_g": 14, "uncertainty": 0.5}],
               "label": "pizza and stew", "confidence": 0.7}
    monkeypatch.setattr(gv, "generate", lambda contents, **kw: _json.dumps(payload))
    monkeypatch.setattr(gv, "types", None, raising=False)
    import types as _t
    fake_types = _t.SimpleNamespace(Part=_t.SimpleNamespace(from_bytes=lambda data, mime_type: {"bytes": len(data)}))
    monkeypatch.setitem(__import__("sys").modules, "google.genai", _t.SimpleNamespace(types=fake_types))
    pe = gv.parse_image_gemini(b"\x00" * 10, "image/jpeg", NOW)
    # pizza carbs (10 g for 2 slices) deviate > 40 % from the table (72 g) -> table wins; the unknown bowl is trusted
    assert abs(pe.event.carbs_g - (72 + 33)) < 0.1
    assert any(i["source"].startswith("table") for i in pe.raw_items)


def test_dispatcher_falls_back_when_gemini_fails(monkeypatch):
    import backend.adapters.parse as P
    monkeypatch.setattr(P, "gemini_available", lambda: True)
    import backend.adapters.gemini_text as gt
    monkeypatch.setattr(gt, "generate", lambda contents, **kw: "this is not json at all")
    pe = P.parse_text("large coffee now", NOW)
    assert pe.parser == "local" and pe.event.type == "caffeine"
    assert P.parser_status()["last_parser"] == "local"
