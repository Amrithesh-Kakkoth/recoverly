import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from tests.test_voice_manager import Rig


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_ice_config_adds_turn_only_when_configured(client, monkeypatch):
    base = (await client.get("/api/ice")).json()["iceServers"]
    assert len(base) == 1 and base[0]["urls"].startswith("stun:")
    monkeypatch.setattr(settings, "turn_ice_urls", "turn:a:3478")
    monkeypatch.setattr(settings, "turn_username", "u")
    monkeypatch.setattr(settings, "turn_credential", "c")
    turn = (await client.get("/api/ice")).json()["iceServers"][1]
    assert turn == {"urls": ["turn:a:3478"], "username": "u", "credential": "c"}


async def test_demo_config_shows_the_sandbox_buyer_only_if_set(client, monkeypatch):
    assert "buyer" not in (await client.get("/api/demo-config")).json()
    monkeypatch.setattr(settings, "demo_buyer_email", "buyer@example.com")
    monkeypatch.setattr(settings, "demo_buyer_password", "pw")
    cfg = (await client.get("/api/demo-config")).json()
    assert cfg["buyer"] == {"email": "buyer@example.com", "password": "pw"}
    assert {"abandon_after_seconds", "voice_enabled"} <= cfg.keys()


async def test_checkout_tells_the_page_how_long_abandonment_takes(client, gw, monkeypatch):
    monkeypatch.setattr(settings, "abandon_after_seconds", 90.0)
    r = await client.post("/shop/checkout", json={"name": "A", "phone": "+919876543210"})
    assert r.json()["abandon_after_seconds"] == 90.0


async def test_stream_resumes_from_since_query(client, fresh_hub):
    ids = [fresh_hub.publish("run:9", "timeline", {"n": i}) for i in range(3)]
    from app.api.runs import events
    got = []
    async for item in events("run:9", ids[0]):
        got.append(json.loads(item["data"])["n"])
        if len(got) == 2:
            break
    assert got == [1, 2]
    # bad channel still rejected on the query-param path
    assert (await client.get("/api/stream/nope?since=0")).status_code == 404


async def test_real_webrtc_handshake_through_the_offer_endpoint(bus):
    """A real aiortc peer (stand-in for the browser) negotiates with Pipecat's real request handler;
    only the audio bot is faked. Proves signalling, SDP and the on_connection hook work."""
    from aiortc import RTCPeerConnection
    from aiortc.mediastreams import AudioStreamTrack
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler

    r = Rig(bus)
    r.mgr.handler = SmallWebRTCRequestHandler()
    connected = asyncio.Event()

    async def bot(sess, conn, deps):
        connected.set()
        await sess.done.wait()

    r.mgr.bot_runner = bot
    app.state.voice, app.state.live_calls = r.mgr, r.live
    rid = await r.seed()
    call_id = await r.mgr.start_call(str(rid), r.STEP)

    pc = RTCPeerConnection()
    pc.addTrack(AudioStreamTrack())
    await pc.setLocalDescription(await pc.createOffer())
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(f"/api/calls/{call_id}/offer?family=F1", json={
                "sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
        assert resp.status_code == 200, resp.text
        ans = resp.json()
        assert ans["type"] == "answer" and "m=audio" in ans["sdp"] and ans["pc_id"]
        await pc.setRemoteDescription(__import__("aiortc").RTCSessionDescription(ans["sdp"], ans["type"]))
        await asyncio.wait_for(connected.wait(), 5)           # server side handed us a connection
        assert r.live.get(call_id).status == "live"
    finally:
        await pc.close()
        await r.mgr.finish(r.live.get(call_id)) if r.live.get(call_id) else None
        await r.mgr._request_handler().close()
        app.state.voice = app.state.live_calls = None


async def test_default_journey_is_valid_and_seeded_once():
    from app.journeys.default import DEFAULT_JOURNEY, ensure_default_journey
    from app.journeys.dsl import Journey
    from app.journeys.lint import lint
    assert lint(Journey.model_validate(DEFAULT_JOURNEY)) == []
    assert await ensure_default_journey() is True
    assert await ensure_default_journey() is False        # never duplicates or overwrites
