import threading

import pytest
import requests
from sqlalchemy import select

from app.core.db import db
from app.payments.models import PayPalOp
from app.payments.paypal_rest import PayPalError
from app.payments.toolkit import ToolkitGateway

ORDER = "1BH65816UV833991S"


def _resp(status, body):
    r = requests.Response()
    r.status_code = status
    r._content = __import__("json").dumps(body).encode()
    r.headers["Content-Type"] = "application/json"
    r.request = requests.Request(
        "GET", "https://x", headers={"Authorization": "Bearer T", "Content-Type": "application/json"}
    ).prepare()
    return r


@pytest.fixture
def fake_http(monkeypatch):
    calls = {"token": 0, "threads": set(), "get_status": 200, "get_body": {"id": ORDER,
             "status": "PAYER_ACTION_REQUIRED", "purchase_units": [{}]}}

    def post(url, **kw):
        calls["threads"].add(threading.get_ident())
        if url.endswith("/v1/oauth2/token"):
            calls["token"] += 1
            return _resp(200, {"access_token": "T", "expires_in": 3600})
        return _resp(201, {"id": ORDER, "status": "PAYER_ACTION_REQUIRED",
                           "links": [{"rel": "payer-action", "href": "https://x/checkout"}]})

    def get(url, **kw):
        calls["threads"].add(threading.get_ident())
        return _resp(calls["get_status"], calls["get_body"])

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    return calls


async def test_calls_run_off_the_event_loop_and_token_is_cached(fake_http):
    tk = ToolkitGateway("id", "secret")
    await tk.get_order(ORDER)
    await tk.get_order(ORDER)
    assert fake_http["token"] == 1
    assert threading.get_ident() not in fake_http["threads"]


async def test_get_order_returns_raw_body_never_the_toolkit_message(fake_http):
    out = await ToolkitGateway("id", "secret").get_order(ORDER)
    assert out["status"] == "PAYER_ACTION_REQUIRED"  # unpaid, though toolkit message says captured
    assert "message" not in out and "successfully captured" not in str(out)


async def test_create_order_goes_through_toolkit(fake_http):
    o = await ToolkitGateway("id", "secret").create_order(
        amount="49.00", currency="USD", return_url="http://localhost:8000/shop/return",
        cancel_url="http://localhost:8000/shop/cancel")
    assert o["id"] == ORDER and o["links"][0]["rel"] == "payer-action"


async def test_http_errors_become_paypal_errors(fake_http):
    fake_http["get_status"] = 404
    fake_http["get_body"] = {"name": "RESOURCE_NOT_FOUND", "details": [{"issue": "INVALID_RESOURCE_ID"}]}
    with pytest.raises(PayPalError) as e:
        await ToolkitGateway("id", "secret").get_order(ORDER)
    assert e.value.status == 404 and "INVALID_RESOURCE_ID" in e.value.issues


async def test_toolkit_calls_are_logged_with_via_badge(fake_http):
    await ToolkitGateway("id", "secret").get_order(ORDER)
    async with db.session() as s:
        ops = (await s.scalars(select(PayPalOp))).all()
    assert [(o.op, o.via, o.status) for o in ops] == [("get_order_details", "agent_toolkit", "ok")]
