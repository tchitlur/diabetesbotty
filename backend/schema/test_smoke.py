from backend.schema.state import State, ALL_FIELDS, FAST_FIELDS
from backend.schema.events import Event
from backend.schema.api import PermissionCard, ForecastResponse


def test_state_roundtrip():
    s = State(glucose=140)
    d = s.to_dict()
    assert set(d) == set(ALL_FIELDS)
    assert State.from_dict(d).glucose == 140
    assert len(s.fast_vector()) == len(FAST_FIELDS)


def test_event_validation():
    e = Event(type="meal", start_time="2025-01-01T12:00", carbs_g=50, source="local")
    assert e.start.hour == 12
    try:
        Event(type="nope", start_time="2025-01-01T12:00")
        assert False
    except ValueError:
        pass


def test_api_models():
    card = PermissionCard(verdict="approved")
    assert card.verdict == "approved"
    f = ForecastResponse(times=[], median=[], p10=[], p90=[], p_hypo_8h=0.1, p_hyper_8h=0.0, tir=0.8)
    assert f.tir == 0.8
