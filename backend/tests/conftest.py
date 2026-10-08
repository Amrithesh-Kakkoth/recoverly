import os

# Tests must never read (or spend) the developer's real .env keys. Set before any app import.
os.environ["RECOVERLY_NO_ENV"] = "1"
for _k in ("DATABASE_URL", "TIME_SCALE", "ABANDON_AFTER_SECONDS", "OPENAI_API_KEY", "LLM_API_KEY",
           "DEEPGRAM_API_KEY", "CARTESIA_API_KEY", "LLM_BASE_URL", "PAYPAL_CLIENT_ID"):
    os.environ.pop(_k, None)

import pytest
from sqlalchemy.pool import StaticPool

from app.core import sse
from app.core.db import db
from app.core.events import EventBus
from app import all_models  # noqa: F401
from app.payments import gateway


# Default: in-memory SQLite (fast, no setup). Set TEST_DATABASE_URL to run the same suite on
# Postgres, which is what production uses:  make test-pg
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
async def database():
    if TEST_DATABASE_URL:
        from sqlalchemy.pool import NullPool

        from app.core.db import Base
        db.configure(TEST_DATABASE_URL, poolclass=NullPool)
        async with db.engine.begin() as conn:      # every test starts from empty tables
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    else:
        db.configure("sqlite+aiosqlite://", poolclass=StaticPool,
                     connect_args={"check_same_thread": False})
        await db.create_all()
    yield
    await db.engine.dispose()


@pytest.fixture(autouse=True)
def fresh_hub(monkeypatch):
    monkeypatch.setattr(sse, "hub", sse.SSEHub())
    return sse.hub


@pytest.fixture
def bus():
    return EventBus()


class FakeGateway:
    """Records calls. `already_captured` orders raise the 422 PayPal returns on re-capture."""

    def __init__(self):
        self.capture_calls: list[tuple[str, str]] = []
        self.orders: dict[str, dict] = {}
        self.capture_status = "COMPLETED"
        self.verify_ok = True
        self._n = 0

    async def create_order(self, *, amount, currency, return_url, cancel_url, request_id):
        self._n += 1
        oid = f"ORD{self._n}"
        order = {"id": oid, "status": "CREATED", "links": [
            {"rel": "payer-action", "href": f"https://sandbox.paypal.com/checkout?token={oid}"}]}
        self.orders[oid] = {"amount": amount, "currency": currency, "captured": False}
        return order

    def _body(self, oid):
        o = self.orders[oid]
        return {"id": oid, "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [{
            "id": f"CAP-{oid}", "status": self.capture_status,
            "amount": {"currency_code": o["currency"], "value": o["amount"]}}]}}]}

    async def capture(self, order_id, request_id):
        from app.payments.paypal_rest import PayPalError
        self.capture_calls.append((order_id, request_id))
        if self.orders[order_id]["captured"]:
            raise PayPalError(422, {"details": [{"issue": "ORDER_ALREADY_CAPTURED"}]})
        self.orders[order_id]["captured"] = True
        return self._body(order_id)

    async def get_order(self, order_id):
        return self._body(order_id)

    async def verify_webhook_signature(self, headers, raw_body, webhook_id):
        return self.verify_ok


@pytest.fixture
def gw():
    g = FakeGateway()
    gateway.set_gateway(g)
    yield g
    gateway.set_gateway(None)
