from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.models import Customer
from app.core.db import db
from app.core.events import DomainEvent
from app.detector.models import AbandonCheck
from app.detector.service import AbandonDetector, schedule
from app.main import app
from app.journeys.models import JourneyRun
from app.journeys.service import save_journey
from tests.journey_fixtures import FakeClock, sample
from tests.test_engine import H


class StatusGateway:
    def __init__(self, status="PAYER_ACTION_REQUIRED"):
        self.status, self.fail, self.gets = status, False, 0

    async def get_order(self, order_id):
        self.gets += 1
        if self.fail:
            raise RuntimeError("paypal down")
        return {"id": order_id, "status": self.status}


class Rig:
    def __init__(self, bus, gw=None, paid=False):
        self.clock, self.gw, self.captured, self.events = FakeClock(), gw or StatusGateway(), [], []
        bus.subscribe("checkout.abandoned", self._on)

        async def capture(order_id):
            self.captured.append(order_id)
            return "captured"

        async def family_paid(_):
            return paid

        self.det = AbandonDetector(event_bus=bus, gateway=self.gw, capture=capture,
                                   family_paid=family_paid, clock=self.clock)

    async def _on(self, e: DomainEvent):
        self.events.append(e)

    async def order(self, oid="ORD1", family="F1", delay=90):
        await schedule(order_id=oid, family_id=family, customer_id="c1", amount="49.00",
                       delay_seconds=delay, now=self.clock())

    async def result(self, oid="ORD1"):
        async with db.session() as s:
            return (await s.scalar(select(AbandonCheck).where(AbandonCheck.order_id == oid))).result


async def test_nothing_fires_before_the_delay_then_unpaid_order_is_abandoned(bus):
    r = Rig(bus)
    await r.order(delay=90)
    r.clock.advance(seconds=89)
    assert await r.det.tick() == 0 and r.events == []
    r.clock.advance(seconds=2)
    assert await r.det.tick() == 1
    e = r.events[0]
    assert (e.type, e.family_id, e.order_id, str(e.amount)) == ("checkout.abandoned", "F1", "ORD1", "49.00")
    assert e.payload == {"customer_id": "c1", "currency": "USD"}
    assert await r.result() == "abandoned"


@pytest.mark.parametrize("status", ["CREATED", "PAYER_ACTION_REQUIRED"])
async def test_both_unpaid_statuses_count_as_abandoned(bus, status):
    r = Rig(bus, StatusGateway(status))
    await r.order()
    r.clock.advance(seconds=91)
    await r.det.tick()
    assert len(r.events) == 1


async def test_approved_but_uncaptured_is_captured_not_abandoned(bus):
    r = Rig(bus, StatusGateway("APPROVED"))
    await r.order()
    r.clock.advance(seconds=91)
    await r.det.tick()
    assert r.captured == ["ORD1"] and r.events == [] and await r.result() == "captured"


@pytest.mark.parametrize("status,result", [("COMPLETED", "paid"), ("VOIDED", "closed")])
async def test_settled_orders_are_left_alone(bus, status, result):
    r = Rig(bus, StatusGateway(status))
    await r.order()
    r.clock.advance(seconds=91)
    await r.det.tick()
    assert r.events == [] and r.captured == [] and await r.result() == result


async def test_family_that_already_paid_elsewhere_is_not_nagged(bus):
    r = Rig(bus, paid=True)
    await r.order()
    r.clock.advance(seconds=91)
    await r.det.tick()
    assert r.events == [] and r.gw.gets == 0 and await r.result() == "paid"


async def test_a_check_fires_exactly_once(bus):
    r = Rig(bus)
    await r.order()
    r.clock.advance(seconds=91)
    await r.det.tick()
    r.clock.advance(seconds=60)
    assert await r.det.tick() == 0 and len(r.events) == 1


async def test_paypal_errors_retry_then_give_up(bus):
    r = Rig(bus)
    r.gw.fail = True
    await r.order()
    r.clock.advance(seconds=91)
    await r.det.tick()                         # attempt 1 fails -> rescheduled +30 s
    assert await r.result() is None and r.events == []
    r.gw.fail = False
    r.clock.advance(seconds=31)
    await r.det.tick()                         # recovers on retry
    assert len(r.events) == 1

    r2 = Rig(bus)
    r2.gw.fail = True
    await r2.order("ORD2", "F2")
    for _ in range(3):
        r2.clock.advance(seconds=100)
        await r2.det.tick()
    assert await r2.result("ORD2") == "error"


async def test_abandon_event_starts_a_journey_run(bus):
    """detector -> bus -> engine: an unpaid order becomes a running journey."""
    h = H(bus)
    async with db.session() as s:
        s.add(Customer(id="c1", name="Asha", call_consent_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        await s.commit()
    await save_journey(sample())
    r = Rig(bus)
    await r.order(family="F7")
    r.clock.advance(seconds=91)
    await r.det.tick()
    async with db.session() as s:
        run = await s.scalar(select(JourneyRun).where(JourneyRun.family_id == "F7"))
    assert run is not None and run.status == "waiting" and run.cursor == "wait1"
    assert h.chan.sent[0][0] == "cart_reminder"


@pytest.fixture
async def client(gw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_checkout_uses_server_side_price_and_schedules_a_check(client, gw):
    r = await client.post("/shop/checkout", json={
        "name": "Asha", "phone": "+919876543210", "sku": "pro-plan",
        "whatsapp_optin": True, "call_consent": True, "amount": "0.01"})  # client amount ignored
    assert r.status_code == 200
    body = r.json()
    assert body["amount"] == "49.00" and gw.orders[body["order_id"]]["amount"] == "49.00"
    assert body["approve_url"].endswith(body["order_id"])
    async with db.session() as s:
        cust = await s.get(Customer, body["customer_id"])
        check = await s.scalar(select(AbandonCheck).where(AbandonCheck.order_id == body["order_id"]))
    assert cust.call_consent_at is not None and cust.phone_e164 == "+919876543210"
    assert check.family_id == body["family_id"] and check.fired_at is None


async def test_checkout_without_consent_records_none(client):
    r = await client.post("/shop/checkout", json={"name": "A", "phone": "+919876543210"})
    async with db.session() as s:
        assert (await s.get(Customer, r.json()["customer_id"])).call_consent_at is None


@pytest.mark.parametrize("payload,code", [
    ({"name": "A", "phone": "98765"}, 422),
    ({"name": "A", "phone": "+919876543210", "sku": "nope"}, 404)])
async def test_checkout_validation(client, payload, code):
    assert (await client.post("/shop/checkout", json=payload)).status_code == code
