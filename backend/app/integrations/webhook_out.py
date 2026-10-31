"""Outbound webhook: tell the merchant's tools (Zapier, Make, n8n, Slack...) when a recovery run ends.

Works with any URL that accepts a JSON POST; for Zapier use a "Catch Hook" trigger. Listens to the same
`run.ended` events the dashboard streams, so the journey engine knows nothing about it. Customer phone
numbers are never included."""
import asyncio
import json
import logging
from decimal import Decimal

import httpx

from app.accounts.service import demo_merchant_id
from app.api.models import Customer
from app.core import sse
from app.core.config import Settings, settings as default_settings
from app.core.db import db
from app.journeys.models import JourneyRun

log = logging.getLogger(__name__)


async def build_payload(run_id: int, cfg: Settings = default_settings) -> dict | None:
    async with db.session() as s:
        run = await s.get(JourneyRun, run_id)
        cust = await s.get(Customer, run.customer_id) if run else None
    if run is None:
        return None
    # OUTBOUND_WEBHOOK_URL is the operator's, so only the demo store's results go to it.
    if run.merchant_id is not None and run.merchant_id != await demo_merchant_id():
        return None
    ctx = run.context_json or {}
    amount = ctx.get("amount")
    name = cust.name if cust else "a customer"
    won = run.close_reason == "recovered"
    money = f"{ctx.get('currency') or 'USD'} {Decimal(amount):.2f}" if amount else ""
    return {
        "event": "recovery.recovered" if won else "recovery.lost",
        "run_id": run.id, "result": run.close_reason, "customer_name": name,
        "amount": amount, "currency": ctx.get("currency"),
        "text": f"Recovered {money} from {name}" if won else f"Could not recover {money} from {name}".replace("  ", " "),
        "run_url": f"{cfg.dashboard_url.rstrip('/')}/runs/{run.id}",
    }


def sample_payload(cfg: Settings = default_settings) -> dict:
    """What a Zap needs to see once to learn the field names."""
    return {"event": "recovery.recovered", "run_id": 0, "result": "recovered", "customer_name": "Asha",
            "amount": "49.00", "currency": "USD", "text": "Recovered USD 49.00 from Asha",
            "run_url": f"{cfg.dashboard_url.rstrip('/')}/runs/0", "sample": True}


async def post(url: str, payload: dict, client: httpx.AsyncClient | None = None, attempts: int = 3) -> bool:
    """POST with a short backoff; never raises (a down webhook must not affect recovery)."""
    owned = client is None
    c = client or httpx.AsyncClient(timeout=10)
    try:
        for i in range(attempts):
            try:
                r = await c.post(url, json=payload)
                if r.status_code < 300:
                    return True
                log.warning("outbound webhook returned %s", r.status_code)
            except httpx.HTTPError as e:
                log.warning("outbound webhook failed: %s", e)
            if i < attempts - 1:
                await asyncio.sleep(0.5 * 2 ** i)
        return False
    finally:
        if owned:
            await c.aclose()


class RecoveryNotifier:
    def __init__(self, cfg: Settings = default_settings, hub: sse.SSEHub | None = None,
                 client: httpx.AsyncClient | None = None) -> None:
        self.cfg, self.hub, self.client = cfg, hub, client
        self._sent: set[int] = set()

    async def run(self) -> None:
        hub = self.hub or sse.hub
        async for item in hub.subscribe("global"):
            if item["event"] != "run.ended":
                continue
            run_id = int(json.loads(item["data"])["run_id"])
            if run_id in self._sent:
                continue
            self._sent.add(run_id)
            payload = await build_payload(run_id, self.cfg)
            if payload:
                await post(self.cfg.outbound_webhook_url, payload, self.client)
