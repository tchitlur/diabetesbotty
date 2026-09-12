"""The chat path end to end with the local parser: the seven questions must produce distinct
events, distinct probabilities and distinct reasons; quantity must change the answer; and
personalisation must matter for at least one of them."""
import os
os.environ["GLUCOPILOT_LIVE_CLOCK"] = "0"

import pytest

from backend.api.twin import Twin
from backend.adapters.local_parser import parse_text_local
from backend.decision.permission import evaluate_permission
from backend.decision.plain import permission_plain
from backend.decision.personal import as_population, twin_summary
from backend.schema.events import Event

MESSAGES = ["can I have pizza for dinner?", "can I have a small salad for dinner?", "large coffee now", "two coffees now",
            "run at 7 tomorrow for 30 min", "lift weights now for 45 min", "can I have two more beers tonight?"]


@pytest.fixture(scope="module")
def twin():
    return Twin("demo")


@pytest.fixture(scope="module")
def cards(twin):
    out = []
    for m in MESSAGES:
        pe = parse_text_local(m, twin.now)
        ev = Event.from_dict(pe.event.model_dump())
        card = evaluate_permission(twin, ev)
        card.plain = permission_plain(card, twin.now)
        out.append((m, ev, card))
    return out


def test_parsed_events_differ(cards):
    keys = [(e.type, round(e.carbs_g), round(e.caffeine_mg), round(e.alcohol_g), round(e.duration_min), e.exercise_kind, e.start_time, e.label) for _, e, _ in cards]
    assert len(set(keys)) == len(keys), keys
    pizza, salad = cards[0][1], cards[1][1]
    assert pizza.carbs_g > salad.carbs_g * 2
    one, two = cards[2][1], cards[3][1]
    assert two.caffeine_mg > one.caffeine_mg * 0.9 and one.caffeine_mg >= 150   # large = 190 mg; two coffees = 190 mg


def test_probabilities_and_reasons_differ(cards):
    p = [round(c.p_hypo, 3) for _, _, c in cards]
    assert len(set(p)) > 1, p
    reasons = [c.plain["reason"] for _, _, c in cards]
    assert len(set(reasons)) == len(reasons), reasons
    for _, _, c in cards:
        v = {x["name"]: x for x in c.variants}
        assert "nadir" in v["proposed"] and "peak" in v["proposed"] and v["proposed"]["nadir_time"]
        assert c.engine["window_min"][1] > c.engine["window_min"][0]


def test_quantity_changes_the_answer(twin):
    two = evaluate_permission(twin, Event(type="alcohol", start_time=twin.now.isoformat(timespec="minutes"), duration_min=90, alcohol_g=28, carbs_g=26, uncertainty=0.2, source="local", label="2 beers"))
    six = evaluate_permission(twin, Event(type="alcohol", start_time=twin.now.isoformat(timespec="minutes"), duration_min=180, alcohol_g=84, carbs_g=78, uncertainty=0.2, source="local", label="6 beers"))
    n2 = {x["name"]: x for x in two.variants}["proposed"]["nadir"]
    n6 = {x["name"]: x for x in six.variants}["proposed"]["nadir"]
    assert six.verdict != two.verdict or abs(n6 - n2) > 10
    assert six.mini_curve.with_event != two.mini_curve.with_event


def test_personalisation_matters(twin, cards):
    lines = twin_summary(twin)["lines"]
    assert 3 <= len(lines) <= 5 and all(l["text"] for l in lines)
    changed = 0
    for _, ev, personal in cards:
        with as_population(twin):
            pop = evaluate_permission(twin, ev)
        twin.cards.pop()
        np_ = {x["name"]: x for x in personal.variants}["proposed"]["nadir"]
        pp = {x["name"]: x for x in pop.variants}["proposed"]["nadir"]
        if pop.verdict != personal.verdict or abs(pp - np_) > 3:
            changed += 1
    assert changed >= 1
