"""Direct REST client: token cache, idempotent capture, webhook verification.
Orders v2 + Notifications v1 only. Sandbox-only is enforced in app.main."""
import json
import time

import httpx


class PayPalError(Exception):
    def __init__(self, status: int, body: dict):
        super().__init__(f"PayPal {status}: {body.get('name') or body}")
        self.status = status
        self.body = body

    @property
    def issues(self) -> set[str]:
        return {d.get("issue", "") for d in self.body.get("details", [])}

    @property
    def not_approved(self) -> bool:
        return self.status == 422 and "ORDER_NOT_APPROVED" in self.issues

    @property
    def already_captured(self) -> bool:
        return self.status == 422 and "ORDER_ALREADY_CAPTURED" in self.issues


def approve_url(order: dict) -> str | None:
    """Accept both rel names; PayPal returns `approve` or `payer-action` depending on flow."""
    for link in order.get("links", []):
        if link.get("rel") in ("approve", "payer-action"):
            return link["href"]
    return None


class PayPalREST:
    def __init__(self, base_url: str, client_id: str, client_secret: str,
                 client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = (client_id, client_secret)
        self._http = client or httpx.AsyncClient(timeout=15)
        self._token: str | None = None
        self._token_exp = 0.0

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_exp - 60:
            return self._token
        r = await self._http.post(f"{self.base_url}/v1/oauth2/token", auth=self._auth,
                                  data={"grant_type": "client_credentials"})
        if r.status_code != 200:
            raise PayPalError(r.status_code, _json(r))
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.monotonic() + int(data.get("expires_in", 300))
        return self._token

    async def _request(self, method: str, path: str, *, request_id: str | None = None,
                       json_body: dict | None = None, content: bytes | None = None) -> dict:
        headers = {"Authorization": f"Bearer {await self._access_token()}",
                   "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        r = await self._http.request(method, f"{self.base_url}{path}", headers=headers,
                                     json=json_body, content=content)
        if r.status_code >= 400:
            raise PayPalError(r.status_code, _json(r))
        return _json(r)

    async def create_order(self, *, amount: str, currency: str, return_url: str,
                           cancel_url: str, request_id: str) -> dict:
        body = {
            "intent": "CAPTURE",
            "purchase_units": [{"amount": {"currency_code": currency, "value": amount}}],
            "payment_source": {"paypal": {"experience_context": {
                "return_url": return_url, "cancel_url": cancel_url,
                "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"}}},
        }
        return await self._request("POST", "/v2/checkout/orders", request_id=request_id,
                                   json_body=body)

    async def get_order(self, order_id: str) -> dict:
        return await self._request("GET", f"/v2/checkout/orders/{order_id}")

    async def capture(self, order_id: str, request_id: str) -> dict:
        return await self._request("POST", f"/v2/checkout/orders/{order_id}/capture",
                                   request_id=request_id, json_body={})

    async def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes,
                                       webhook_id: str) -> bool:
        """The event must be sent byte-for-byte as received, so splice the raw body in
        rather than re-serialising a parsed dict (re-serialising breaks the CRC check)."""
        head = json.dumps({
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": webhook_id,
        })[:-1]
        content = head.encode() + b',"webhook_event":' + raw_body + b"}"
        data = await self._request("POST", "/v1/notifications/verify-webhook-signature",
                                   content=content)
        return data.get("verification_status") == "SUCCESS"


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {"message": r.text}
