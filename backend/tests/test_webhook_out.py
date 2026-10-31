import asyncio
import json
from datetime import datetime, timezone

import httpx
from httpx import ASGITransport, AsyncClient

from app.api.models import Customer
from app.core import sse
from app.core.config import Settings
from app.core.db import db
from app.integrations.webhook_out import RecoveryNotifier, build_payload, post
from app.journeys.models import JourneyRecord, JourneyRun, JourneyVersion
from app.main import app

CFG = Settings(outbound_webhook_url="https://hooks.example.com/x", dashboard_url="https://dash.example.com")


async def make_run(reason="recovered"):
    async with db.session() as s:
        s.add(Customer(id="c1", name="Asha", phone_e164="+919876543210"))
        j = JourneyRecord(name="j", trigger_event="checkout.abandoned")
        s.add(j)
        await s.flush()
        v = JourneyVersion(journey_id=j.id, version=1, definition_json={})
        s.add(v)
        await s.flush()
        r = JourneyRun(journey_version_id=v.id, customer_id="c1", family_id="f1", status="done", cursor="x",
                       close_reason=reason, started_at=datetime.now(timezone.utc),
                       context_json={"amount": "49.00", "currency": "USD"})
        s.add(r)
        await s.commit()
        return r.id


async def test_payload_has_the_story_but_never_the_phone_number():
    p = await build_payload(await make_run(), CFG)
    assert p["event"] == "recovery.recovered" and p["text"] == "Recovered USD 49.00 from Asha"
    assert p["run_url"] == f"https://dash.example.com/runs/{p['run_id']}"
    assert "919876543210" not in json.dumps(p)


async def test_lost_run_payload():
    p = await build_payload(await make_run("lost"), CFG)
    assert p["event"] == "recovery.lost" and p["text"].startswith("Could not recover")


async def test_notifier_posts_once_per_ended_run():
    rid = await make_run()
    got = []

    def handler(req):
        got.append(json.loads(req.content))
        return httpx.Response(200)

    hub = sse.SSEHub()
    n = RecoveryNotifier(CFG, hub, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    task = asyncio.create_task(n.run())
    await asyncio.sleep(0)
    hub.publish("global", "run.started", {"run_id": rid})
    hub.publish("global", "run.ended", {"run_id": rid})
    hub.publish("global", "run.ended", {"run_id": rid})
    for _ in range(50):
        await asyncio.sleep(0.01)
        if got:
            break
    task.cancel()
    assert [g["run_id"] for g in got] == [rid]


async def test_post_retries_then_gives_up_without_raising():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500)

    c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await post("https://x", {}, c, attempts=2) is False and len(calls) == 2


async def test_test_endpoint(monkeypatch):
    from app.api import integrations
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        monkeypatch.setattr(integrations.settings, "outbound_webhook_url", "")
        assert (await c.post("/api/integrations/webhook/test")).status_code == 409
        monkeypatch.setattr(integrations.settings, "outbound_webhook_url", "https://x")
        sent = []

        async def fake_post(url, payload, client=None, attempts=3):
            sent.append(payload)
            return True

        monkeypatch.setattr(integrations, "post", fake_post)
        assert (await c.post("/api/integrations/webhook/test")).json() == {"ok": True}
        assert sent[0]["sample"] is True and (await c.get("/api/integrations")).json() == {"outbound_webhook": True}
