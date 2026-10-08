from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.api.models import Customer
from app.core.db import db
from app.core.events import DomainEvent
from app.journeys.engine import JourneyEngine
from app.journeys.models import JourneyRun, StepRun, Timer, TimelineEvent
from app.journeys.service import save_journey
from app.journeys.timers import TimerLoop
from tests.journey_fixtures import FakeClock, sample

IST = timezone(timedelta(hours=5, minutes=30))


class Calls:
    def __init__(self):
        self.dialed: list[str] = []

    async def start_call(self, run_id, step):
        self.dialed.append(f"call-{len(self.dialed) + 1}")
        return self.dialed[-1]


class Chan:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def send(self, customer_id, template, vars):
        self.sent.append((template, vars))
        return f"msg-{len(self.sent)}"


class Links:
    async def pay_link(self, family_id, amount, currency="USD"):
        return f"https://pay.test/{family_id}"


class H:
    """Test harness wiring an engine to fakes and a controllable clock."""

    def __init__(self, bus, family_paid=None):
        self.clock, self.calls, self.chan = FakeClock(), Calls(), Chan()
        self.engine = JourneyEngine(channels={"web_inbox": self.chan}, call_manager=self.calls,
                                    pay_links=Links(), clock=self.clock,
                                    family_paid=family_paid)
        self.engine.register(bus)
        self.timers = TimerLoop(self.engine)
        self.bus = bus

    async def start(self, definition=None, scale=1.0, family="F1", **ctx):
        _, v = await save_journey(definition or sample())
        return await self.engine.start_run(version_id=v, customer_id="c1", family_id=family,
                                           time_scale=scale, context={"amount": "49.00", **ctx})

    async def run(self, rid):
        async with db.session() as s:
            return await s.get(JourneyRun, rid)

    async def timeline(self, rid):
        async with db.session() as s:
            return [e.kind for e in (await s.scalars(select(TimelineEvent).where(
                TimelineEvent.run_id == rid).order_by(TimelineEvent.id))).all()]

    async def tick(self, **advance):
        self.clock.advance(**advance)
        return await self.timers.tick()

    async def pay(self, family="F1"):
        await self.bus.publish(DomainEvent(type="payment.captured", family_id=family,
                                           capture_id=f"CAP-{family}-{self.clock.t.timestamp()}",
                                           amount=Decimal("49.00"), source="capture_response"))

    async def complete_call(self, rid, call_id, outcome):
        await self.bus.publish(DomainEvent(type="call.completed", payload={
            "run_id": rid, "call_id": call_id, "outcome": outcome}))


@pytest.fixture(autouse=True)
async def customer():
    async with db.session() as s:
        s.add(Customer(id="c1", name="Asha", call_consent_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        await s.commit()


@pytest.fixture
def h(bus):
    return H(bus)


async def test_paid_on_call_routes_to_thanks_even_if_agent_reports_no_answer(h):
    rid = await h.start(scale=60)  # PT30M wait -> 30 s
    assert h.chan.sent[0][0] == "cart_reminder" and h.chan.sent[0][1]["pay_url"] == "https://pay.test/F1"
    assert (await h.run(rid)).status == "waiting"

    assert await h.tick(seconds=31) == 1
    assert (await h.run(rid)).status == "in_call" and h.calls.dialed == ["call-1"]

    await h.pay()  # mid-call: routing is deferred, the run stays on the call
    run = await h.run(rid)
    assert run.status == "in_call" and run.cursor == "call1"

    await h.complete_call(rid, "call-1", "no_answer")  # ctx.paid beats outcome routing
    run = await h.run(rid)
    assert (run.status, run.close_reason) == ("done", "recovered")
    assert [t for t, _ in h.chan.sent] == ["cart_reminder", "thank_you"]
    kinds = await h.timeline(rid)
    for k in ("run.started", "message.sent", "wait.started", "call.dialed",
              "event.payment_captured", "call.completed", "run.ended"):
        assert k in kinds
    async with db.session() as s:
        assert {r.status for r in (await s.scalars(select(StepRun))).all()} == {"done"}


async def test_payment_during_wait_skips_the_call(h):
    rid = await h.start()
    await h.pay()
    run = await h.run(rid)
    assert (run.status, run.close_reason) == ("done", "recovered") and h.calls.dialed == []
    async with db.session() as s:
        assert (await s.scalars(select(Timer).where(Timer.fired_at.is_(None)))).all() == []


async def test_no_answer_retries_after_scaled_delay_then_gives_up(h):
    rid = await h.start(scale=3600)  # wait 0.5 s, retry_after 2 s
    await h.tick(seconds=1)
    await h.complete_call(rid, "call-1", "no_answer")
    run = await h.run(rid)
    assert run.status == "waiting" and h.calls.dialed == ["call-1"]
    assert await h.tick(seconds=1) == 0           # retry not due yet (2 s)
    assert await h.tick(seconds=2) == 1
    assert h.calls.dialed == ["call-1", "call-2"] and (await h.run(rid)).attempts_json == {"call1": 2}
    await h.complete_call(rid, "call-2", "no_answer")  # attempts exhausted -> default
    run = await h.run(rid)
    assert (run.status, run.close_reason) == ("done", "lost")


async def test_promised_to_pay_waits_then_loses_on_timeout(h):
    rid = await h.start(scale=1800)  # wait1 1 s, wait2 48 s
    await h.tick(seconds=2)
    await h.complete_call(rid, "call-1", "promised_to_pay")
    assert (await h.run(rid)).cursor == "wait2"
    await h.tick(seconds=60)
    assert (await h.run(rid)).close_reason == "lost"


async def test_promise_then_payment_during_wait2_recovers(h):
    rid = await h.start(scale=1800)
    await h.tick(seconds=2)
    await h.complete_call(rid, "call-1", "promised_to_pay")
    await h.pay()
    assert (await h.run(rid)).close_reason == "recovered"


async def test_call_window_uses_real_time_and_defers_not_skips(bus):
    h = H(bus)
    h.clock.t = datetime(2026, 10, 8, 22, 0, tzinfo=IST)  # 22:00 IST, outside 09-21
    d = sample(**{"settings": {"call_window": {"start": "09:00", "end": "21:00", "tz": "Asia/Kolkata"}}})
    rid = await h.start(d, scale=3600)
    await h.tick(seconds=1)                              # wait elapsed (scaled), window closed
    run = await h.run(rid)
    assert run.status == "waiting" and h.calls.dialed == []
    assert "call.deferred" in await h.timeline(rid)
    assert await h.tick(hours=10) == 0                   # 08:00 IST next day: still closed
    assert await h.tick(hours=1, seconds=1) == 1         # 09:00 IST: dials
    assert h.calls.dialed == ["call-1"]


async def test_pre_dial_guard_skips_call_when_family_already_paid(bus):
    async def paid(_):
        return True

    h = H(bus, family_paid=paid)
    rid = await h.start(scale=3600)
    await h.tick(seconds=1)
    run = await h.run(rid)
    assert (run.status, run.close_reason) == ("done", "recovered") and h.calls.dialed == []


async def test_no_consent_means_no_call(h):
    async with db.session() as s:
        (await s.get(Customer, "c1")).call_consent_at = None
        await s.commit()
    rid = await h.start(scale=3600)
    await h.tick(seconds=1)
    run = await h.run(rid)
    assert (run.close_reason, h.calls.dialed) == ("lost", [])
    assert "call.skipped" in await h.timeline(rid)


async def test_one_active_run_per_family(h):
    assert await h.start() is not None
    assert await h.start() is None


async def test_stale_or_duplicate_call_completion_is_ignored(h):
    rid = await h.start(scale=3600)
    await h.tick(seconds=1)
    await h.complete_call(rid, "some-other-call", "paid")
    assert (await h.run(rid)).status == "in_call"
    await h.complete_call(rid, "call-1", "no_answer")
    before = (await h.run(rid)).attempts_json
    await h.complete_call(rid, "call-1", "paid")          # already handled
    assert (await h.run(rid)).attempts_json == before


async def test_timers_survive_a_restart(bus):
    h1 = H(bus)
    rid = await h1.start(scale=3600)                      # parked on a persisted wait timer
    h2 = H(bus)                                           # "new process": fresh engine, same DB
    h2.clock.t = h1.clock.t + timedelta(seconds=5)
    assert await h2.timers.tick() == 1
    assert h2.calls.dialed == ["call-1"] and (await h2.run(rid)).status == "in_call"


async def test_abandon_event_starts_a_run_and_respects_trigger_filter(h):
    await save_journey(sample())
    low = DomainEvent(type="checkout.abandoned", family_id="F9", amount=Decimal("10.00"),
                      payload={"customer_id": "c1"})
    high = DomainEvent(type="checkout.abandoned", family_id="F8", amount=Decimal("49.00"),
                       payload={"customer_id": "c1"})
    await h.bus.publish(low)
    assert await h.engine._active_run_for("F9") is None   # below amount_gte 20
    await h.bus.publish(high)
    assert await h.engine._active_run_for("F8") is not None
