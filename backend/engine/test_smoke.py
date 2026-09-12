from backend.schema.state import State
from backend.engine.simulate import simulate


def test_stub_simulate_shape():
    tr = simulate(State(), [], {}, horizon_min=480)
    assert len(tr.t_min) == 97
    assert "glucose" in tr.series
    assert tr.max_glucose >= tr.min_glucose
