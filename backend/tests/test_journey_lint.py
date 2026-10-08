import pytest

from app.journeys.dsl import Journey
from app.journeys.lint import lint
from app.journeys.service import InvalidJourney, save_journey
from app.journeys.timeutil import next_window_start, parse_duration
from tests.journey_fixtures import sample
from datetime import datetime, timedelta, timezone


def errs(**mods):
    return lint(Journey.model_validate(sample(**mods)))


def test_sample_journey_is_valid():
    assert errs() == []


def test_goto_must_resolve():
    assert any("does not exist" in e for e in errs(**{"steps.nudge.next": "nowhere"}))


def test_unreachable_step_is_flagged():
    d = sample()
    d["steps"]["orphan"] = {"type": "end", "result": "lost"}
    assert any("orphan: unreachable" in e for e in lint(Journey.model_validate(d)))


def test_every_path_must_reach_an_end():
    d = sample()
    d["steps"]["wait2"]["next"] = "wait2"  # loops forever
    out = lint(Journey.model_validate(d))
    assert any("wait2: cannot reach an End" in e for e in out)
    assert any("unbounded loop" in e for e in out)


def test_loop_through_a_call_is_bounded_and_allowed():
    assert errs() == []  # call1 -> call1 retry loop is capped by max_attempts


def test_offer_cannot_exceed_merchant_limit():
    assert any("exceeds merchant limit" in e for e in errs(**{"steps.call1.offer": {"max": 50}}))


def test_unknown_tool_rejected():
    assert any("tools not allowed" in e for e in errs(**{"steps.call1.tools": ["wire_money"]}))


def test_payment_journey_needs_on_events_handler():
    assert any("no on_events handler" in e for e in errs(on_events=[]))


def test_retries_need_retry_after():
    assert any("retry_after" in e for e in errs(**{"steps.call1.retry_after": None}))


def test_durations():
    assert parse_duration("PT30M") == timedelta(minutes=30)
    assert parse_duration("P1DT2H") == timedelta(days=1, hours=2)
    with pytest.raises(ValueError):
        parse_duration("30 minutes")


def test_call_window_defers_to_next_start_never_skips():
    w = {"start": "09:00", "end": "21:00", "tz": "Asia/Kolkata"}
    ist = lambda h, m=0, d=8: datetime(2026, 10, d, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert next_window_start(ist(10), w) is None
    assert next_window_start(ist(22), w) == ist(9, d=9).astimezone(timezone.utc)   # tomorrow 09:00
    assert next_window_start(ist(7), w) == ist(9).astimezone(timezone.utc)         # today 09:00


async def test_save_journey_lints_and_versions():
    jid, v1 = await save_journey(sample())
    _, v2 = await save_journey(sample(), journey_id=jid)
    assert v2 != v1
    with pytest.raises(InvalidJourney):
        await save_journey(sample(on_events=[]))
