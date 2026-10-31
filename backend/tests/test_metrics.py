from datetime import datetime, timedelta, timezone
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.core.db import db
from app.journeys.models import JourneyRun, JourneyVersion, TimelineEvent
from app.journeys.models import JourneyRecord
from app.main import app
from app.payments.models import PaymentObject
from app.voice.models import Call

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


async def get():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return (await c.get("/api/metrics")).json()


async def test_empty():
    m = await get()
    assert m["runs_total"] == 0 and m["recovery_rate"] is None and m["recovered_revenue"] == "0"


async def test_recovery_kpis():
    async with db.session() as s:
        j = JourneyRecord(name="j", trigger_event="checkout.abandoned")
        s.add(j)
        await s.flush()
        v = JourneyVersion(journey_id=j.id, version=1, definition_json={})
        s.add(v)
        await s.flush()

        def run(fam, status, reason):
            r = JourneyRun(journey_version_id=v.id, customer_id="c", family_id=fam, status=status,
                           cursor="x", close_reason=reason, started_at=T0)
            s.add(r)
            return r

        won, lost, live = run("f1", "done", "recovered"), run("f2", "done", "lost"), run("f3", "waiting", None)
        await s.flush()
        s.add(TimelineEvent(run_id=won.id, kind="event.payment_captured", ts=T0 + timedelta(seconds=90)))
        s.add_all([PaymentObject(kind="capture", paypal_id="C1", family_id="f1", status="COMPLETED",
                                 amount=Decimal("49.00"), currency="USD"),
                   PaymentObject(kind="capture", paypal_id="C2", family_id="f2", status="PENDING",
                                 amount=Decimal("29.00"), currency="USD"),
                   Call(id="call1", run_id=won.id), Call(id="call2", run_id=lost.id)])
        await s.commit()
    m = await get()
    assert (m["runs_total"], m["runs_active"], m["recovered"]) == (3, 1, 1)
    assert m["recovery_rate"] == 0.5
    assert Decimal(m["recovered_revenue"]) == Decimal("49.00") and m["currency"] == "USD"
    assert m["median_seconds_to_pay"] == 90
    assert m["calls"] == 2 and m["calls_per_recovered"] == 2
