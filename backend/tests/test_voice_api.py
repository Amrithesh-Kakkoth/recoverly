import asyncio
import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.db import db
from app.main import app
from app.voice.manager import VoiceCallManager
from app.voice.models import Call
from app.voice.registry import LiveCalls
from app.voice.session import CallSession
from tests.test_voice_manager import CFG, FakeHandler, Rig
from tests.test_voice_core import session


async def test_completion_is_reported_even_if_persisting_fails(bus):
    """Regression: the journey run parks on call.completed, so it must always fire."""
    r = Rig(bus)
    ghost = session(call_id="never-saved")          # no Call row: the DB update will raise
    r.live.register(ghost)
    await r.mgr.finish(ghost, no_answer=True)
    assert [e.payload["call_id"] for e in r.completed] == ["never-saved"]


def test_pipeline_builds_with_the_installed_pipecat():
    """Guards against Pipecat API drift: constructs every service + the pipeline (no network)."""
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

    from app.voice import pipeline
    from tests.test_voice_core import Deps

    async def build():
        cfg = Settings(**CFG)
        s = session()
        task = pipeline.build_task(s, SmallWebRTCConnection(ice_servers=pipeline.ice_servers(cfg)),
                                   Deps(), cfg)
        return s, task

    s, task = asyncio.run(build())
    assert s.task is task and s.gate is not None
    schema = pipeline.tools_schema(s)
    assert sorted(f.name for f in schema.standard_tools) == sorted(s.tools)


def test_turn_servers_come_from_config():
    from app.voice import pipeline
    cfg = Settings(**CFG, turn_ice_urls="turn:a:3478, turns:b:5349", turn_username="u", turn_credential="c")
    servers = pipeline.ice_servers(cfg)
    assert servers[0].urls.startswith("stun:") and servers[1].urls == ["turn:a:3478", "turns:b:5349"]
    assert (servers[1].username, servers[1].credential) == ("u", "c")
    assert len(pipeline.ice_servers(Settings(**CFG))) == 1


@pytest.fixture
async def client(bus):
    r = Rig(bus)
    app.state.voice, app.state.live_calls = r.mgr, r.live
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, r
    app.state.voice = app.state.live_calls = None


OFFER = {"sdp": "v=0", "type": "offer"}


async def test_offer_answers_a_ringing_call_once(client):
    c, r = client
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    ok = await c.post(f"/api/calls/{call_id}/offer?family=F1", json=OFFER)
    assert ok.status_code == 200 and ok.json()["type"] == "answer"
    assert (await c.post(f"/api/calls/{call_id}/offer?family=F1", json=OFFER)).status_code == 409
    assert (await c.post("/api/calls/call_nope/offer", json=OFFER)).status_code == 404
    await r.mgr.finish(r.live.get(call_id))


async def test_call_detail_live_then_ended(client):
    c, r = client
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    sess = r.live.get(call_id)
    sess.transcript.append({"role": "user", "text": "hi"})
    live = (await c.get(f"/api/calls/{call_id}?family=F1")).json()
    assert live["status"] == "ringing" and live["transcript"][0]["text"] == "hi"
    await r.mgr.finish(sess, no_answer=False)
    done = (await c.get(f"/api/calls/{call_id}?family=F1")).json()
    assert done["status"] == "ended" and done["outcome"] == "needs_human"  # spoke, no hint, low confidence
    assert (await c.get("/api/calls/call_nope")).status_code == 404


async def test_voice_endpoints_report_unconfigured_voice():
    app.state.voice = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/calls/x/offer", json=OFFER)
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


def test_voice_enabled_accepts_any_llm_key_and_host():
    base = dict(deepgram_api_key="d", cartesia_api_key="c")
    assert not Settings(**base).voice_enabled
    assert Settings(**base, openai_api_key="o").voice_enabled
    s = Settings(**base, llm_api_key="gsk", llm_base_url="https://api.groq.com/openai/v1")
    assert s.voice_enabled and s.llm_key == "gsk"


def test_pipeline_builds_against_a_non_openai_endpoint():
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

    from app.voice import pipeline
    from tests.test_voice_core import Deps

    async def build():
        cfg = Settings(deepgram_api_key="d", cartesia_api_key="c", llm_api_key="gsk",
                       llm_base_url="https://api.groq.com/openai/v1", llm_model="llama-3.3-70b-versatile")
        return pipeline.build_task(session(), SmallWebRTCConnection(ice_servers=[]), Deps(), cfg)

    assert asyncio.run(build()) is not None


async def test_classifier_uses_json_mode_on_non_openai_hosts_and_strict_schema_on_openai():
    import httpx

    from app.voice.tagger import openai_classifier
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append((str(req.url), body["response_format"]["type"]))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"label": "paid", "confidence": 0.9, "summary": "s", "objections": []})}}]})

    tr = [{"role": "user", "text": "hi"}]
    for base in ("https://api.groq.com/openai/v1", ""):
        c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert (await openai_classifier("k", "m", base, client=c)(tr, None))["label"] == "paid"
    assert seen == [("https://api.groq.com/openai/v1/chat/completions", "json_object"),
                    ("https://api.openai.com/v1/chat/completions", "json_schema")]


def test_record_turn_builds_the_transcript_and_skips_empty_turns():
    from app.voice.pipeline import record_turn
    s = session()
    record_turn(s, "assistant", "  Hi, I'm Maya, an AI assistant.  ")
    record_turn(s, "user", "send me the link")
    record_turn(s, "assistant", "", False)            # LLM returned zero tokens
    record_turn(s, "user", None)
    record_turn(s, "assistant", "Sure, I've sent it", interrupted=True)
    assert s.transcript == [{"role": "assistant", "text": "Hi, I'm Maya, an AI assistant."},
                            {"role": "user", "text": "send me the link"},
                            {"role": "assistant", "text": "Sure, I've sent it", "interrupted": True}]


async def test_a_call_that_used_tools_is_never_tagged_no_answer(bus):
    """Regression from the first real call: empty transcript + tool calls was tagged no_answer."""
    from tests.test_voice_manager import Rig
    r = Rig(bus)
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)
    s = r.live.get(call_id)
    s.hint = "promised_to_pay"
    s.tool_calls.append({"tool": "send_payment_link", "args": {}, "result": {"ok": True}})
    await r.mgr.finish(s)
    assert r.completed[0].payload["outcome"] != "no_answer"


async def test_boot_marks_unfinished_calls_interrupted(bus):
    from app.voice.manager import mark_interrupted_calls
    from tests.test_voice_manager import Rig
    r = Rig(bus)
    rid = await r.seed()
    ringing = await r.mgr.start_call(str(rid), r.STEP)
    done = await r.mgr.start_call(str(await r.seed("F2")), r.STEP)
    await r.mgr.finish(r.live.get(done), no_answer=True)
    assert await mark_interrupted_calls() == 1
    async with db.session() as s:
        assert (await s.get(Call, ringing)).status == "interrupted"
        assert (await s.get(Call, done)).status == "ended"
    for ts in r.mgr._timers.values():
        for t in ts:
            t.cancel()
