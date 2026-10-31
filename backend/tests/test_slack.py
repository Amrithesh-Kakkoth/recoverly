import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.accounts.models import Merchant
from app.api import integrations
from app.api.models import Customer
from app.core import sse
from app.core.config import Settings
from app.core.db import db
from app.integrations.webhook_out import RecoveryNotifier, slack_message
from app.journeys.models import JourneyRecord, JourneyRun, JourneyVersion
from app.main import app
from datetime import datetime, timezone
from tests.conftest import sign_in

URL = "https://hooks.slack.com/services/T000/B000/secret"
CFG = Settings(dashboard_url="https://dash.example.com")


def browser():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def make_run(merchant_id, name="Asha", reason="recovered"):
    async with db.session() as s:
        s.add(Customer(id=f"c{merchant_id}", merchant_id=merchant_id, name=name))
        j = JourneyRecord(name="j", trigger_event="checkout.abandoned", merchant_id=merchant_id)
        s.add(j)
        await s.flush()
        v = JourneyVersion(journey_id=j.id, version=1, definition_json={})
        s.add(v)
        await s.flush()
        r = JourneyRun(merchant_id=merchant_id, journey_version_id=v.id, customer_id=f"c{merchant_id}",
                       family_id=f"f{merchant_id}", status="done", cursor="x", close_reason=reason,
                       started_at=datetime.now(timezone.utc), context_json={"amount": "49.00", "currency": "USD"})
        s.add(r)
        await s.commit()
        return r.id


async def test_connect_never_echoes_the_url_and_disconnect_clears_it():
    async with browser() as c:
        await sign_in(c)
        assert (await c.get("/api/integrations")).json()["slack"] is False
        r = await c.put("/api/integrations/slack", json={"url": f"  {URL} "})
        assert r.status_code == 200 and "secret" not in r.text
        status = await c.get("/api/integrations")
        assert status.json()["slack"] is True and "secret" not in status.text
        assert "secret" not in (await c.get("/api/auth/me")).text
        await c.delete("/api/integrations/slack")
        assert (await c.get("/api/integrations")).json()["slack"] is False


@pytest.mark.parametrize("url", [
    "http://hooks.slack.com/services/T/B/x", "https://evil.example.com/services/T/B/x",
    "https://hooks.slack.com.evil.com/services/T/B/x", "http://169.254.169.254/latest/meta-data",
    "https://hooks.slack.com/services/T/B/x?redirect=http://evil", "https://hooks.slack.com/other/x",
])
async def test_only_slack_webhook_urls_are_accepted(url):
    async with browser() as c:
        await sign_in(c)
        assert (await c.put("/api/integrations/slack", json={"url": url})).status_code == 422


async def test_settings_need_a_session_and_test_message_needs_a_connection(monkeypatch):
    async with browser() as c:
        assert (await c.put("/api/integrations/slack", json={"url": URL})).status_code == 401
        assert (await c.delete("/api/integrations/slack")).status_code == 401
        await sign_in(c)
        assert (await c.post("/api/integrations/slack/test")).status_code == 409
        await c.put("/api/integrations/slack", json={"url": URL})
        sent = []

        async def fake_post(url, payload, client=None, attempts=3):
            sent.append((url, payload))
            return True

        monkeypatch.setattr(integrations, "post", fake_post)
        assert (await c.post("/api/integrations/slack/test")).status_code == 200
        assert sent[0][0] == URL and "Test Store" in sent[0][1]["text"]

        async def failing_post(url, payload, client=None, attempts=3):
            return False

        monkeypatch.setattr(integrations, "post", failing_post)
        assert (await c.post("/api/integrations/slack/test")).status_code == 502


async def test_message_is_built_for_the_runs_merchant_and_escapes_customer_names():
    async with browser() as c:
        mine, other = await sign_in(c, "a@example.com"), None
    async with db.session() as s:
        (await s.get(Merchant, mine)).slack_webhook_url = URL
        s.add(Merchant(id=99, email="b@example.com", password_hash="!", store_name="B"))
        await s.commit()
    rid = await make_run(mine, name="<!channel> & co")
    url, message = await slack_message(rid, CFG)
    assert url == URL and "&lt;!channel&gt; &amp; co" in message["text"] and "<!channel>" not in message["text"]
    assert "Recovered USD 49.00" in message["text"] and f"<https://dash.example.com/runs/{rid}|" in message["text"]
    assert other is None and await slack_message(await make_run(99), CFG) is None      # not connected


async def test_notifier_posts_to_each_merchants_own_channel_once():
    async with db.session() as s:
        s.add_all([Merchant(id=1, email="a@example.com", password_hash="!", store_name="A", slack_webhook_url=URL + "A"),
                   Merchant(id=2, email="b@example.com", password_hash="!", store_name="B", slack_webhook_url=URL + "B")])
        await s.commit()
    run_a, run_b = await make_run(1), await make_run(2, reason="lost")
    got = []

    def handler(req):
        got.append((str(req.url), json.loads(req.content)["text"]))
        return httpx.Response(200)

    hub = sse.SSEHub()
    task = asyncio.create_task(RecoveryNotifier(CFG, hub, httpx.AsyncClient(transport=httpx.MockTransport(handler))).run())
    await asyncio.sleep(0)
    for rid in (run_a, run_a, run_b):
        hub.publish("global", "run.ended", {"run_id": rid})
    for _ in range(100):
        await asyncio.sleep(0.01)
        if len(got) >= 2:
            break
    await asyncio.sleep(0.05)
    task.cancel()
    assert [g[0] for g in got] == [URL + "A", URL + "B"]
    assert got[0][1].startswith(":tada: Recovered") and got[1][1].startswith("Could not recover")
