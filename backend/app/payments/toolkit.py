"""PayPal Agent Toolkit (Python) behind the same interface as the REST client.

Toolkit gotchas handled here:
- it uses blocking `requests`, which would stutter live audio on the event loop -> every call
  runs in `asyncio.to_thread`;
- it fetches a new OAuth token on every call -> `_CachedClient` caches it;
- `get_order_details` / `pay_order` return a canned "successfully captured" message even when
  nothing was captured -> we return only the raw PayPal body, never the toolkit's message;
- `create_order` sets no PAY_NOW and no PayPal-Request-Id, and `pay_order` has no idempotency
  key -> capture stays on REST (see PayPalGateway)."""
import asyncio
import json
import threading
import time

import requests
from paypal_agent_toolkit.shared.api import PayPalAPI
from paypal_agent_toolkit.shared.configuration import Context
from paypal_agent_toolkit.shared.paypal_client import PayPalClient

from app.payments.ops import logged
from app.payments.paypal_rest import PayPalError, PayPalREST


class _CachedClient(PayPalClient):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_exp = 0.0

    def get_access_token(self):
        with self._lock:
            if self._token and time.monotonic() < self._token_exp - 60:
                return self._token
            r = requests.post(f"{self.base_url}/v1/oauth2/token", auth=(self.client_id, self.secret),
                              data={"grant_type": "client_credentials"},
                              headers={"Accept": "application/json"}, timeout=15)
            r.raise_for_status()
            data = r.json()
            self._token = data["access_token"]
            self._token_exp = time.monotonic() + int(data.get("expires_in", 300))
            return self._token


class ToolkitGateway:
    def __init__(self, client_id: str, client_secret: str) -> None:
        ctx = Context(sandbox=True, source="recoverly")
        self._api = PayPalAPI(client_id=client_id, secret=client_secret, context=ctx)
        self._api._paypal_client = _CachedClient(client_id=client_id, secret=client_secret,
                                                 context=ctx)

    async def _run(self, method: str, params: dict) -> dict:
        async with logged(method, "agent_toolkit"):
            try:
                out = await asyncio.to_thread(self._api.run, method, params)
            except requests.HTTPError as e:
                body = {}
                if e.response is not None:
                    try:
                        body = e.response.json()
                    except ValueError:
                        body = {"message": e.response.text}
                raise PayPalError(e.response.status_code if e.response is not None else 0, body)
        return json.loads(out)

    async def create_order(self, *, amount: str, currency: str, return_url: str,
                           cancel_url: str, request_id: str | None = None) -> dict:
        """`request_id` is accepted for interface parity but the toolkit cannot send it."""
        total = float(amount)
        return await self._run("create_order", {
            "currency_code": currency, "return_url": return_url, "cancel_url": cancel_url,
            "items": [{"name": "Order", "quantity": 1, "item_cost": total, "item_total": total}],
        })

    async def get_order(self, order_id: str) -> dict:
        return (await self._run("get_order_details", {"order_id": order_id}))["raw"]

    async def pay_order(self, order_id: str) -> dict:
        """Non-idempotent capture. Not used by capture_once; kept for the toolkit demo path."""
        return (await self._run("pay_order", {"order_id": order_id}))["raw"]

    async def show_subscription_details(self, subscription_id: str) -> dict:
        return await self._run("show_subscription_details", {"subscription_id": subscription_id})


class PayPalGateway:
    """Routes per the design: toolkit for create/read, REST for capture + webhook verify."""

    def __init__(self, rest: PayPalREST, toolkit: ToolkitGateway) -> None:
        self.rest, self.toolkit = rest, toolkit

    async def create_order(self, **kw) -> dict:
        return await self.toolkit.create_order(**kw)

    async def get_order(self, order_id: str) -> dict:
        return await self.toolkit.get_order(order_id)

    async def show_subscription_details(self, subscription_id: str) -> dict:
        return await self.toolkit.show_subscription_details(subscription_id)

    async def capture(self, order_id: str, request_id: str) -> dict:
        return await self.rest.capture(order_id, request_id)

    async def verify_webhook_signature(self, headers, raw_body, webhook_id) -> bool:
        return await self.rest.verify_webhook_signature(headers, raw_body, webhook_id)
