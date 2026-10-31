import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.models import Customer
from app.core.db import db
from app.main import app
from app.voice.models import Call
from app.voice.phone import signature, twiml
from tests.test_voice_manager import Rig, until

PHONE = dict(call_via_phone=True, twilio_account_sid="AC1", twilio_auth_token="tok",
             twilio_voice_from="+15550001111", public_base_url="https://demo.example.com")


class FakeDialer:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def dial(self, to, call_id, token):
        if self.fail:
            raise RuntimeError("twilio down")
        self.calls.append((to, call_id, token))
        return "CA123"


async def phone_rig(bus, dialer=None, **cfg):
    r = Rig(bus, **PHONE, **cfg)
    r.mgr.dialer = dialer or FakeDialer()
    rid = await r.seed()
    async with db.session() as s:
        (await s.get(Customer, "c1")).phone_e164 = "+919876543210"
        await s.commit()
    return r, rid


async def test_phone_call_dials_the_customer_and_does_not_ring_the_browser(bus, fresh_hub):
    r, rid = await phone_rig(bus)
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    s = r.live.get(call_id)
    assert (s.transport, s.status) == ("twilio", "ringing") and s.token
    assert r.mgr.dialer.calls == [("+919876543210", call_id, s.token)]
    assert "call.ringing" not in [e["event"] for e in fresh_hub._log[f"run:{rid}"]]
    async with db.session() as sess:
        call = await sess.get(Call, call_id)
        assert (call.transport, call.twilio_sid) == ("twilio", "CA123")
    for t in r.mgr._timers[call_id]:
        t.cancel()


async def test_failed_dial_is_no_answer_not_a_hung_run(bus):
    r, rid = await phone_rig(bus, FakeDialer(fail=True))
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    await until(lambda: r.completed)
    assert [(e.payload["call_id"], e.payload["outcome"]) for e in r.completed] == [(call_id, "no_answer")]


async def test_status_callback_for_an_unanswered_call_finishes_it(bus):
    r, rid = await phone_rig(bus)
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    await r.mgr.on_phone_status(call_id, "no-answer")
    assert [e.payload["outcome"] for e in r.completed] == ["no_answer"]


async def test_media_stream_needs_the_right_token_then_runs_the_agent(bus):
    ran = []

    async def phone_bot(sess, ws, serializer, deps):
        ran.append(sess.status)

    r, rid = await phone_rig(bus)
    r.mgr.phone_runner = phone_bot
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    token = r.live.get(call_id).token
    with pytest.raises(LookupError):
        await r.mgr.answer_phone(call_id, "wrong", object(), "MZ1", "CA123")
    await r.mgr.answer_phone(call_id, token, object(), "MZ1", "CA123")
    assert ran == ["live"] and [e.payload["call_id"] for e in r.completed] == [call_id]


async def test_twiml_webhook_checks_token_and_twilio_signature(bus):
    r, rid = await phone_rig(bus)
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    token = r.live.get(call_id).token
    app.state.voice = r.mgr
    path = f"/twilio/voice/{call_id}?token={token}"
    sig = signature("tok", f"https://demo.example.com{path}", {"CallSid": "CA123"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.post(path, data={"CallSid": "CA123"}, headers={"x-twilio-signature": sig})
        assert ok.status_code == 200 and ok.text == twiml(r.mgr.cfg, call_id, token)
        assert "wss://demo.example.com/twilio/ws" in ok.text
        assert (await c.post(path, data={"CallSid": "CA123"}, headers={"x-twilio-signature": "x"})).status_code == 403
        assert (await c.post(f"/twilio/voice/{call_id}?token=nope", data={})).status_code == 404
    for t in r.mgr._timers[call_id]:
        t.cancel()
    app.state.voice = None


def test_phone_pipeline_builds_with_the_installed_pipecat():
    """Guards against Pipecat API drift for the Twilio websocket transport (no network)."""
    from pipecat.serializers.twilio import TwilioFrameSerializer

    from app.core.config import Settings
    from app.voice import pipeline
    from tests.test_voice_core import Deps, session
    from tests.test_voice_manager import CFG

    class WS:  # the transport only stores it until a client connects
        pass

    async def build():
        ser = TwilioFrameSerializer("MZ1", "CA1", "AC1", "tok")
        return pipeline.build_phone_task(session(), WS(), ser, Deps(), Settings(**CFG))

    import asyncio
    assert asyncio.run(build()) is not None
