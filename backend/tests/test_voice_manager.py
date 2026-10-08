import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.api.models import Customer
from app.core.config import Settings
from app.core.db import db
from app.core.events import DomainEvent
from app.journeys.service import save_journey
from app.voice.gate import InjectionGate
from app.voice.manager import VoiceCallManager
from app.voice.models import Call, Outcome
from app.voice.registry import LiveCalls
from app.voice.tools import ToolBox
from tests.journey_fixtures import sample
from tests.test_engine import H
from tests.test_voice_core import Deps

CFG = dict(openai_api_key="x", deepgram_api_key="x", cartesia_api_key="x")


class FakeHandler:
    """Stands in for SmallWebRTCRequestHandler: 'negotiates', then hands over a connection."""

    async def handle_web_request(self, request, on_connection):
        await on_connection(object())
        return {"sdp": "answer", "type": "answer", "pc_id": "pc1"}


class Rig:
    def __init__(self, bus, bot=None, **cfg):
        self.completed: list[DomainEvent] = []
        bus.subscribe("call.completed", self._on)
        self.live, self.deps = LiveCalls(), Deps()
        self.live.register_bus(bus)
        self.mgr = VoiceCallManager(
            live=self.live, deps=self.deps, classify=None, bot_runner=bot or self.idle_bot,
            request_handler=FakeHandler(), event_bus=bus,
            cfg=Settings(**{**CFG, "ring_timeout_seconds": 5, "call_max_seconds": 60, **cfg}))

    async def _on(self, e):
        self.completed.append(e)

    @staticmethod
    async def idle_bot(sess, conn, deps):
        sess.gate = InjectionGate(lambda msgs: asyncio.sleep(0))
        await sess.done.wait()

    async def seed(self, family="F1", amount="49.00"):
        from app.journeys.models import JourneyRun, JourneyVersion
        async with db.session() as s:
            if not await s.get(Customer, "c1"):
                s.add(Customer(id="c1", name="Asha",
                               call_consent_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
            if not await s.get(JourneyVersion, 1):
                s.add(JourneyVersion(id=1, journey_id=1, version=1, definition_json=sample()))
            run = JourneyRun(journey_version_id=1, customer_id="c1", family_id=family, cursor="call1",
                             status="in_call", started_at=datetime.now(timezone.utc),
                             context_json={"amount": amount, "currency": "USD"})
            s.add(run)
            await s.commit()
            return run.id

    STEP = {"objective": "Help", "tools": ["send_payment_link", "check_payment_status", "end_call"],
            "offer": {"kind": "discount_pct", "max": 10}}


async def until(cond, timeout=2.0):
    """Poll instead of sleeping: completion involves DB writes whose timing varies."""
    end = asyncio.get_running_loop().time() + timeout
    while not cond() and asyncio.get_running_loop().time() < end:
        await asyncio.sleep(0.01)
    assert cond(), "condition not reached in time"


async def settle(rounds=5):
    for _ in range(rounds):
        await asyncio.sleep(0)


async def test_start_call_builds_session_from_the_run_and_never_completes_synchronously(bus):
    r = Rig(bus)
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    s = r.live.get(call_id)
    assert (s.status, s.family_id, s.customer_name, s.amount, s.offer_max_pct) == (
        "ringing", "F1", "Asha", Decimal("49.00"), 10.0)
    assert s.tools == ["send_payment_link", "check_payment_status", "end_call"]
    assert r.completed == []
    async with db.session() as sess:
        assert (await sess.get(Call, call_id)).status == "ringing"
    for t in r.mgr._timers[call_id]:
        t.cancel()


async def test_unanswered_call_times_out_as_no_answer(bus):
    r = Rig(bus, ring_timeout_seconds=0)
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    await until(lambda: r.completed)
    assert [(e.payload["call_id"], e.payload["outcome"]) for e in r.completed] == [(call_id, "no_answer")]
    assert r.live.count() == 0
    async with db.session() as s:
        assert (await s.scalar(select(Outcome.label))) == "no_answer"


async def test_capacity_and_kill_switch_refuse_the_call_without_blocking_the_engine(bus):
    r = Rig(bus, max_concurrent_calls=1)
    first = await r.seed("F1")
    second = await r.seed("F2")
    await r.mgr.start_call(str(first), r.STEP)           # takes the only slot
    busy_id = await r.mgr.start_call(str(second), r.STEP)
    assert r.completed == []                              # not synchronous
    await until(lambda: r.completed)
    assert [e.payload["call_id"] for e in r.completed] == [busy_id]
    assert r.completed[0].payload["outcome"] == "no_answer"
    for ts in r.mgr._timers.values():
        for t in ts:
            t.cancel()

    k = Rig(bus, kill_switch=True)
    third = await k.seed("F3")
    await k.mgr.start_call(str(third), k.STEP)
    await until(lambda: k.completed)
    assert k.live.count() == 0 and k.completed[0].payload["outcome"] == "no_answer"


async def test_answer_runs_the_bot_and_a_hangup_without_speaking_is_no_answer(bus):
    r = Rig(bus)
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    out = await r.mgr.answer(call_id, object())
    assert out["type"] == "answer" and r.live.get(call_id).status == "live"
    with pytest.raises(ValueError):
        await r.mgr.answer(call_id, object())             # already answered
    await r.mgr.finish(r.live.get(call_id))
    await settle()
    assert r.completed[0].payload["outcome"] == "no_answer"
    with pytest.raises(LookupError):
        await r.mgr.answer("call_nope", object())


async def test_finish_is_idempotent(bus):
    r = Rig(bus)
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    s = r.live.get(call_id)
    await r.mgr.finish(s, no_answer=True)
    await r.mgr.finish(s, no_answer=True)
    assert len(r.completed) == 1


async def test_time_cap_ends_a_live_call(bus):
    r = Rig(bus, call_max_seconds=0)

    async def bot(sess, conn, deps):
        sess.transcript.append({"role": "user", "text": "hello"})
        await sess.done.wait()

    r.mgr.bot_runner = bot
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    s = r.live.get(call_id)
    await r.mgr.answer(call_id, object())
    await until(lambda: r.completed)                        # the cap ended the call
    assert s.ended_reason == "time_cap"
    await r.mgr.finish(s)                                   # pipeline teardown calls this too
    assert len(r.completed) == 1


async def test_payment_mid_call_end_to_end(bus):
    """engine -> manager -> bot(fake) -> PayPal event -> registry/gate -> tool -> tagger -> engine."""
    h = H(bus)
    pushed: list[list[dict]] = []

    async def bot(sess, conn, deps):
        async def push(msgs):
            pushed.append(msgs)
        sess.gate = InjectionGate(push)
        sess.transcript.append({"role": "user", "text": "ok send me the link"})
        tb = ToolBox(sess, deps)
        link = await tb.dispatch("send_payment_link", {})          # agent sends the link
        assert link["ok"]
        await bus.publish(DomainEvent(type="payment.captured", family_id=sess.family_id,
                                      capture_id="CAP1", amount=Decimal("49.00"),
                                      source="capture_response"))  # customer pays
        assert (await tb.dispatch("check_payment_status", {}))["status"] == "paid"
        await tb.dispatch("end_call", {"outcome_hint": "no_answer"})  # agent hint is wrong on purpose
        sess.done.set()

    deps = Deps()
    live = LiveCalls()
    live.register_bus(bus)
    mgr = VoiceCallManager(live=live, deps=deps, classify=None, bot_runner=bot,
                           request_handler=FakeHandler(), event_bus=bus,
                           cfg=Settings(**CFG, ring_timeout_seconds=30))
    h.engine.call_manager = mgr
    async with db.session() as s:
        s.add(Customer(id="c1", name="Asha", call_consent_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        await s.commit()
    rid = await h.start(scale=3600)
    await h.tick(seconds=1)                                  # wait elapsed -> dial -> ringing
    run = await h.run(rid)
    assert run.status == "in_call"
    call_id = run.context_json["call_id"]

    await mgr.answer(call_id, object())                       # judge picks up
    for _ in range(50):
        if (await h.run(rid)).status == "done":
            break
        await asyncio.sleep(0.02)

    run = await h.run(rid)
    assert (run.status, run.close_reason) == ("done", "recovered")
    assert pushed and pushed[0][0]["content"] == "[PAYPAL EVENT] Payment captured: $49.00"
    assert [t for t, _ in deps.sent] == ["pay_link"]
    async with db.session() as s:
        out = await s.scalar(select(Outcome))
        call = await s.get(Call, call_id)
    assert (out.label, out.overridden_by) == ("paid", "family_paid")  # override beat the bad hint
    assert call.status == "ended" and call.tool_calls_json[0]["tool"] == "send_payment_link"
