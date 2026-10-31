import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.accounts import service
from app.accounts.models import AuthSession, Merchant
from app.api.models import Customer
from app.channels.web_inbox import WebInbox
from app.core.config import settings
from app.core.db import db
from app.core.events import DomainEvent
from app.journeys.models import JourneyRecord, JourneyRun
from app.journeys.service import save_journey
from app.main import app
from app.voice.models import Call
from tests.conftest import sign_in
from tests.journey_fixtures import sample
from tests.test_engine import H

PASSWORD = "correct-horse-1"


def browser():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture(autouse=True)
def no_lockouts():
    service._failures.clear()


async def test_signup_signs_in_and_starts_with_a_journey():
    async with browser() as c:
        r = await c.post("/api/auth/signup", json={"email": " Owner@Example.com ", "password": PASSWORD,
                                                   "store_name": "Acme"})
        assert r.status_code == 201 and r.json()["email"] == "owner@example.com"
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert (await c.get("/api/auth/me")).json()["store_name"] == "Acme"
        assert len((await c.get("/api/journeys")).json()) == 1


async def test_passwords_and_session_tokens_are_never_stored_in_the_clear():
    async with browser() as c:
        await sign_in(c)
        token = c.cookies["recoverly_session"]
    async with db.session() as s:
        merchant = await s.scalar(select(Merchant))
        stored = await s.scalar(select(AuthSession.token_hash))
    assert PASSWORD not in merchant.password_hash and merchant.password_hash.startswith("scrypt$")
    assert stored != token


@pytest.mark.parametrize("body,code", [
    ({"email": "not-an-email", "password": PASSWORD, "store_name": "A"}, 422),
    ({"email": "a@b.co", "password": "short", "store_name": "A"}, 422),
    ({"email": "a@b.co", "password": PASSWORD, "store_name": ""}, 422),
])
async def test_signup_validation(body, code):
    async with browser() as c:
        assert (await c.post("/api/auth/signup", json=body)).status_code == code


async def test_duplicate_email_wrong_password_logout_and_expiry():
    async with browser() as c:
        await sign_in(c)
        assert (await c.post("/api/auth/signup", json={"email": "owner@example.com", "password": PASSWORD,
                                                       "store_name": "B"})).status_code == 409
        token = c.cookies["recoverly_session"]
        assert (await c.post("/api/auth/logout")).status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 401
        assert await service.merchant_for_token(token) is None      # the old cookie is dead server-side
    async with browser() as c:
        bad = await c.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong-password"})
        nobody = await c.post("/api/auth/login", json={"email": "no@example.com", "password": "wrong-password"})
        assert bad.status_code == nobody.status_code == 401 and bad.json() == nobody.json()
        assert (await c.post("/api/auth/login", json={"email": "owner@example.com",
                                                      "password": PASSWORD})).status_code == 200


async def test_repeated_failures_lock_the_email_out():
    async with browser() as c:
        await sign_in(c)
    async with browser() as c:
        body = {"email": "owner@example.com", "password": "wrong-password"}
        for _ in range(service.MAX_FAILURES):
            assert (await c.post("/api/auth/login", json=body)).status_code == 401
        body["password"] = PASSWORD
        assert (await c.post("/api/auth/login", json=body)).status_code == 429


@pytest.mark.parametrize("method,path", [
    ("get", "/api/runs"), ("get", "/api/metrics"), ("get", "/api/journeys"), ("get", "/api/integrations"),
    ("get", "/api/customers/c1/messages"), ("get", "/api/stream/merchant"),
    ("post", "/api/journeys/compile"), ("post", "/api/journeys"),
])
async def test_dashboard_routes_need_a_session(method, path):
    async with browser() as c:
        r = await getattr(c, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 401


async def test_the_internal_global_stream_is_not_served():
    async with browser() as c:
        await sign_in(c)
        assert (await c.get("/api/stream/global")).status_code == 404
        assert (await c.get("/api/stream/merchant:1")).status_code == 404


async def _run_for(bus, merchant_id, family):
    """A real run owned by merchant_id, plus a call on it."""
    async with db.session() as s:
        if not await s.get(Customer, f"cust-{family}"):
            s.add(Customer(id=f"cust-{family}", merchant_id=merchant_id, name="Asha",
                           phone_e164="+919876543210", call_consent_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
            await s.commit()
    _, version = await save_journey(sample(), merchant_id=merchant_id)
    run_id = await H(bus).engine.start_run(version_id=version, customer_id=f"cust-{family}", family_id=family,
                                           time_scale=3600, context={"amount": "49.00", "currency": "USD"})
    async with db.session() as s:
        s.add(Call(id=f"call-{family}", run_id=run_id, status="ended"))
        await s.commit()
    return run_id


async def test_merchants_cannot_see_each_others_data(bus):
    async with browser() as a, browser() as b, browser() as anon:
        mine, theirs = await sign_in(a, "a@example.com"), await sign_in(b, "b@example.com")
        run_a = await _run_for(bus, mine, "family-a")
        assert [r["id"] for r in (await a.get("/api/runs")).json()] == [run_a]
        assert (await a.get("/api/runs")).json()[0]["customer_name"] == "Asha"
        assert (await a.get(f"/api/runs/{run_a}")).status_code == 200
        assert (await a.get("/api/calls/call-family-a")).status_code == 200
        assert (await a.get("/api/customers/cust-family-a/messages")).status_code == 200

        assert (await b.get("/api/runs")).json() == []
        for path in (f"/api/runs/{run_a}", "/api/calls/call-family-a", "/api/customers/cust-family-a/messages",
                     f"/api/stream/run:{run_a}", "/api/stream/call:call-family-a"):
            assert (await b.get(path)).status_code == 404, path
            assert (await anon.get(path)).status_code in (401, 404), path
        assert (await b.post("/api/calls/call-family-a/offer", json={"sdp": "v=0", "type": "offer"})).status_code in (404, 503)

        journey_a = (await a.get("/api/journeys")).json()[0]
        taken = await b.post("/api/journeys", json={"definition": sample(), "journey_id": journey_a["id"]})
        assert taken.status_code == 404
        assert theirs != mine


async def test_a_try_it_visitor_only_gets_the_run_their_checkout_made(bus):
    async with browser() as owner, browser() as visitor:
        run_id = await _run_for(bus, await sign_in(owner), "a-long-unguessable-family")
        assert (await visitor.get("/shop/runs/a-long-unguessable-family")).json() == {"run_id": run_id}
        assert (await visitor.get(f"/api/runs/{run_id}?family=a-long-unguessable-family")).status_code == 200
        assert (await visitor.get("/api/calls/call-a-long-unguessable-family?family=a-long-unguessable-family")).status_code == 200
        assert (await visitor.get(f"/api/runs/{run_id}?family=wrong")).status_code == 404
        assert (await visitor.get(f"/api/runs/{run_id}")).status_code == 404
        assert (await visitor.get("/api/runs")).status_code == 401


async def test_checkout_belongs_to_the_signed_in_merchant_else_the_demo_store(gw):
    await service.ensure_demo_merchant()
    demo = await service.demo_merchant_id()
    payload = {"name": "A", "phone": "+919876543210", "call_consent": True}
    async with browser() as anon, browser() as signed_in:
        visitor_order = (await anon.post("/shop/checkout", json=payload)).json()
        merchant_id = await sign_in(signed_in)
        own_order = (await signed_in.post("/shop/checkout", json=payload)).json()
    assert len(visitor_order["family_id"]) == 32
    async with db.session() as s:
        assert (await s.get(Customer, visitor_order["customer_id"])).merchant_id == demo
        assert (await s.get(Customer, own_order["customer_id"])).merchant_id == merchant_id


async def test_an_abandoned_cart_only_runs_its_own_stores_journey(bus):
    h = H(bus)
    h.engine.channels["whatsapp"] = WebInbox("whatsapp")  # what the default journey sends through
    async with browser() as a, browser() as b:
        mine, other = await sign_in(a, "a@example.com"), await sign_in(b, "b@example.com")
    async with db.session() as s:
        s.add(Customer(id="shopper", merchant_id=mine, name="Asha"))
        await s.commit()
    await h.engine.on_trigger(DomainEvent(type="checkout.abandoned", family_id="F9", order_id="O9", amount="49.00",
                                          payload={"customer_id": "shopper", "currency": "USD"}))
    async with db.session() as s:
        run = await s.scalar(select(JourneyRun).where(JourneyRun.family_id == "F9"))
        owner = await s.scalar(select(JourneyRecord.merchant_id).order_by(JourneyRecord.id).limit(1))
    assert run is not None and run.merchant_id == mine and other != mine and owner == mine


async def test_merchant_stream_carries_only_your_runs(bus, fresh_hub):
    async with browser() as a, browser() as b:
        mine, other = await sign_in(a, "a@example.com"), await sign_in(b, "b@example.com")
    await _run_for(bus, mine, "family-a")
    assert fresh_hub.latest_id(f"merchant:{mine}") > 0 and fresh_hub.latest_id(f"merchant:{other}") == 0
    log = fresh_hub._log[f"merchant:{mine}"]
    assert json.loads(log[0]["data"])["kind"] == "run.started"


async def test_demo_merchant_password_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "demo_merchant_password", "")
    await service.ensure_demo_merchant()
    login = {"email": settings.demo_merchant_email, "password": "judges-password-1"}
    async with browser() as c:
        assert (await c.post("/api/auth/login", json=login)).status_code == 401
        monkeypatch.setattr(settings, "demo_merchant_password", "judges-password-1")
        await service.ensure_demo_merchant()
        assert (await c.post("/api/auth/login", json=login)).status_code == 200
        assert len((await c.get("/api/journeys")).json()) == 1
        monkeypatch.setattr(settings, "demo_merchant_password", "")
        await service.ensure_demo_merchant()
    async with browser() as c:
        assert (await c.post("/api/auth/login", json=login)).status_code == 401
