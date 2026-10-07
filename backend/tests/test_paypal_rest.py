import json

import httpx
import pytest

from app.payments.paypal_rest import PayPalError, PayPalREST


def make(handler):
    return PayPalREST("https://api-m.sandbox.paypal.com", "id", "secret",
                      client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_token_is_cached_across_calls():
    hits = {"token": 0}

    def handler(req):
        if req.url.path == "/v1/oauth2/token":
            hits["token"] += 1
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        return httpx.Response(200, json={"id": "O1"})

    gw = make(handler)
    await gw.get_order("O1")
    await gw.get_order("O1")
    assert hits["token"] == 1


async def test_capture_sends_request_id_and_parses_422():
    def handler(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        assert req.headers["PayPal-Request-Id"] == "capture:O1"
        return httpx.Response(422, json={"details": [{"issue": "ORDER_ALREADY_CAPTURED"}]})

    with pytest.raises(PayPalError) as e:
        await make(handler).capture("O1", "capture:O1")
    assert e.value.already_captured


async def test_verify_sends_raw_body_unmodified():
    raw = b'{"id":"WH-1",  "event_type":"X",\n "resource":{"a":1}}'  # odd spacing must survive
    seen = {}

    def handler(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        seen["body"] = req.content
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    ok = await make(handler).verify_webhook_signature({"paypal-transmission-id": "t"}, raw, "WH")
    assert ok and raw in seen["body"]
    assert json.loads(seen["body"])["webhook_id"] == "WH"
