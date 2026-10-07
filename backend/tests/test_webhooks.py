import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.events import EventBus
from app.main import app
from app.payments import service as payments
from app.payments.service import capture_once, create_order
from app.webhooks import router as wh


def cap_event(event_id, order_id, cap_id):
    return {"id": event_id, "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
        "id": cap_id, "amount": {"currency_code": "USD", "value": "49.00"},
        "supplementary_data": {"related_ids": {"order_id": order_id}}}}


@pytest.fixture
async def client(gw, bus, monkeypatch):
    monkeypatch.setattr(wh, "bus", bus)
    monkeypatch.setattr(settings, "paypal_webhook_id", "WH-1")
    payments.register(bus)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def post(client, body):
    return await client.post("/webhooks/paypal", content=json.dumps(body),
                             headers={"paypal-transmission-id": "x"})


async def test_duplicate_event_id_is_acked_and_processed_once(client, gw, bus):
    seen = []
    bus.subscribe("payment.captured", lambda e: _append(seen, e))
    o = await create_order("F1", "49.00")
    ev = cap_event("WH-EV-1", o["order_id"], "CAP-1")
    assert (await post(client, ev)).json() == {"ok": True}
    assert (await post(client, ev)).json() == {"ok": True, "duplicate": True}
    assert len(seen) == 1 and seen[0].family_id == "F1" and seen[0].source == "webhook"


async def _append(lst, e):
    lst.append(e)


async def test_bad_signature_is_rejected_and_not_routed(client, gw, bus):
    seen = []
    bus.subscribe("payment.captured", lambda e: _append(seen, e))
    gw.verify_ok = False
    o = await create_order("F1", "49.00")
    r = await post(client, cap_event("WH-EV-2", o["order_id"], "CAP-2"))
    assert r.status_code == 400 and seen == []


async def test_simulator_event_accepted_only_when_allowed(client, gw, monkeypatch):
    gw.verify_ok = False
    monkeypatch.setattr(settings, "allow_simulator", True)
    o = await create_order("F1", "49.00")
    assert (await post(client, cap_event("WH-EV-3", o["order_id"], "CAP-3"))).status_code == 200


async def test_webhook_and_capture_response_dedupe_to_one_event(client, gw, bus):
    seen = []
    bus.subscribe("payment.captured", lambda e: _append(seen, e))
    o = await create_order("F1", "49.00")
    await capture_once(o["order_id"], event_bus=bus)  # capture response arrives first
    await post(client, cap_event("WH-EV-4", o["order_id"], f"CAP-{o['order_id']}"))
    assert len(seen) == 1 and seen[0].source == "capture_response"


async def test_order_approved_webhook_triggers_capture_once(client, gw, bus):
    o = await create_order("F1", "49.00")
    await post(client, {"id": "WH-EV-5", "event_type": "CHECKOUT.ORDER.APPROVED",
                        "resource": {"id": o["order_id"]}})
    assert gw.capture_calls == [(o["order_id"], f"capture:{o['order_id']}")]


async def test_malformed_body_is_400(client):
    r = await client.post("/webhooks/paypal", content=b"not json")
    assert r.status_code == 400


async def test_reprocess_pending_picks_up_unprocessed_rows(client, gw, bus):
    seen = []
    bus.subscribe("payment.captured", lambda e: _append(seen, e))
    o = await create_order("F1", "49.00")
    original = wh.process_event

    async def boom(_):
        return None  # simulate crash after the row was stored

    wh.process_event = boom
    try:
        await post(client, cap_event("WH-EV-6", o["order_id"], "CAP-6"))
    finally:
        wh.process_event = original
    assert seen == []
    assert await wh.reprocess_pending() == 1
    assert len(seen) == 1
