import asyncio
import json
from datetime import datetime, timezone

import pytest
from sse_starlette.event import ServerSentEvent
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.models import Customer
from app.api.runs import events
from app.channels.models import Message
from app.channels.web_inbox import WebInbox
from app.core import sse
from app.core.db import db
from app.journeys.service import save_journey
from app.main import app
from tests.journey_fixtures import sample
from tests.test_engine import H


async def take(agen, n):
    out = []
    async for item in agen:
        out.append(item)
        if len(out) == n:
            break
    return out


async def test_hub_delivers_in_order_and_isolates_channels():
    hub = sse.SSEHub()
    sub = asyncio.create_task(take(hub.subscribe("run:1"), 2))
    await asyncio.sleep(0)
    hub.publish("run:2", "x", {"n": 0})
    hub.publish("run:1", "a", {"n": 1})
    hub.publish("run:1", "b", {"n": 2})
    got = await asyncio.wait_for(sub, 1)
    assert [g["event"] for g in got] == ["a", "b"] and got[0]["id"] < got[1]["id"]


async def test_reconnect_replays_only_what_was_missed():
    hub = sse.SSEHub()
    ids = [hub.publish("run:1", "e", {"n": i}) for i in range(4)]
    got = await asyncio.wait_for(take(hub.subscribe("run:1", last_id=ids[1]), 2), 1)
    assert [json.loads(g["data"])["n"] for g in got] == [2, 3]


async def test_event_published_during_replay_is_not_lost_or_duplicated():
    hub = sse.SSEHub()
    hub.publish("run:1", "e", {"n": 0})
    sub = hub.subscribe("run:1", last_id=0)
    first = await sub.__anext__()
    hub.publish("run:1", "e", {"n": 1})
    second = await asyncio.wait_for(sub.__anext__(), 1)
    assert (json.loads(first["data"])["n"], json.loads(second["data"])["n"]) == (0, 1)
    await sub.aclose()


async def test_subscriber_is_cleaned_up_on_disconnect():
    hub = sse.SSEHub()
    gen = hub.subscribe("run:1")
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    assert hub._subs["run:1"]
    task.cancel()  # client disconnect
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "run:1" not in hub._subs


@pytest.fixture(autouse=True)
async def customer():
    async with db.session() as s:
        s.add(Customer(id="c1", name="Asha", call_consent_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        await s.commit()


async def test_engine_publishes_timeline_after_commit_and_run_edges_to_global(bus, fresh_hub):
    h = H(bus)
    h.engine.hub = fresh_hub
    run_events, global_events = [], []

    async def watch(ch, sink):
        async for it in fresh_hub.subscribe(ch):
            sink.append(it)

    t1 = asyncio.create_task(watch("run:1", run_events))
    t2 = asyncio.create_task(watch("global", global_events))
    await asyncio.sleep(0)
    rid = await h.start()
    await h.pay()
    await asyncio.sleep(0.05)
    t1.cancel(); t2.cancel()
    kinds = [json.loads(e["data"])["kind"] for e in run_events if e["event"] == "timeline"]
    assert rid == 1 and kinds[0] == "run.started" and kinds[-1] == "run.ended" and "message.sent" in kinds
    assert [e["event"] for e in global_events] == ["run.started", "run.ended"]
    # every published timeline id exists in the DB: nothing was announced before it was durable
    from app.journeys.models import TimelineEvent
    async with db.session() as s:
        stored = {e.id for e in (await s.scalars(select(TimelineEvent))).all()}
    assert {json.loads(e["data"])["id"] for e in run_events if e["event"] == "timeline"} <= stored


async def test_web_inbox_stores_message_with_run_id_and_pushes_it(fresh_hub):
    inbox = WebInbox(hub=fresh_hub)
    sub = asyncio.create_task(take(fresh_hub.subscribe("run:5"), 1))
    await asyncio.sleep(0)
    await inbox.send("c1", "cart_reminder", {"run_id": 5, "pay_url": "https://pay.test/F1"})
    got = json.loads((await asyncio.wait_for(sub, 1))[0]["data"])
    assert got["run_id"] == 5 and "https://pay.test/F1" in got["body"]
    async with db.session() as s:
        assert (await s.scalar(select(Message.run_id))) == 5


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_run_snapshot_then_stream_has_no_gap(bus, client, fresh_hub):
    h = H(bus)
    h.engine.channels["web_inbox"] = WebInbox(hub=fresh_hub)
    _, v = await save_journey(sample())
    rid = await h.engine.start_run(version_id=v, customer_id="c1", family_id="F1",
                                   time_scale=3600, context={"amount": "49.00"})
    snap = (await client.get(f"/api/runs/{rid}")).json()
    assert snap["status"] == "waiting" and snap["customer_id"] == "c1"
    assert [e["kind"] for e in snap["timeline"]][0] == "run.started"
    assert snap["messages"][0]["body"].startswith("Hi! You left something")
    assert "phone" not in json.dumps(snap)

    await h.tick(seconds=1)                                  # engine moves after the snapshot
    missed = await asyncio.wait_for(take(events(f"run:{rid}", snap["last_event_id"]), 1), 1)
    assert json.loads(missed[0]["data"])["kind"] in ("step.entered", "call.dialed")


async def test_api_lists_runs_messages_and_rejects_bad_channels(bus, client, fresh_hub):
    h = H(bus)
    h.engine.channels["web_inbox"] = WebInbox(hub=fresh_hub)
    _, v = await save_journey(sample())
    await h.engine.start_run(version_id=v, customer_id="c1", family_id="F1", context={"amount": "49.00"})
    assert [r["family_id"] for r in (await client.get("/api/runs")).json()] == ["F1"]
    assert len((await client.get("/api/customers/c1/messages")).json()) == 1
    assert (await client.get("/api/runs/999")).status_code == 404
    assert (await client.get("/api/stream/run:abc")).status_code == 404
    assert (await client.get("/api/stream/../etc")).status_code in (404, 405)


async def test_stream_items_survive_the_real_sse_encoder(fresh_hub):
    """Regression: sse-starlette rejects non-string ids, which crashed every live stream."""
    fresh_hub.publish("run:3", "timeline", {"kind": "run.started"})
    item = (await asyncio.wait_for(take(events("run:3", None), 1), 1))[0]
    wire = ServerSentEvent(**item).encode().decode()
    assert "event: timeline" in wire and "id: 1" in wire and "run.started" in wire


async def test_api_timestamps_carry_a_utc_offset(bus, client):
    """Regression: naive timestamps rendered hours off in the browser."""
    h = H(bus)
    _, v = await save_journey(sample())
    rid = await h.engine.start_run(version_id=v, customer_id="c1", family_id="F1", context={"amount": "49.00"})
    snap = (await client.get(f"/api/runs/{rid}")).json()
    for ts in [snap["started_at"], snap["timeline"][0]["ts"]]:
        assert ts.endswith("+00:00")
