"""POST /webhooks/paypal: store raw (unique event id) -> verify -> 200 fast -> route async.
Boot reprocesses rows whose processed_at is NULL."""
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import db
from app.core.events import bus
from app.payments.gateway import get_gateway
from app.payments.normalize import webhook_event
from app.payments.paypal_rest import PayPalError
from app.payments.service import family_of
from app.webhooks.models import WebhookEvent

log = logging.getLogger(__name__)
router = APIRouter()


async def verify(headers: dict[str, str], raw: bytes) -> str:
    """verified | simulated | failed. Simulator events never verify, so they are accepted
    only behind ALLOW_SIMULATOR and tagged `simulated` so the UI can badge them."""
    ok = False
    if settings.paypal_webhook_id:
        ok = await get_gateway().verify_webhook_signature(headers, raw, settings.paypal_webhook_id)
    if ok:
        return "verified"
    return "simulated" if settings.allow_simulator else "failed"


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request, background: BackgroundTasks) -> dict:
    raw = await request.body()
    try:
        body = json.loads(raw)
        event_id, event_type = body["id"], body["event_type"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "malformed event")

    async with db.session() as s:
        if await s.scalar(select(WebhookEvent.id).where(WebhookEvent.paypal_event_id == event_id)):
            return {"ok": True, "duplicate": True}

    try:
        verification = await verify({k.lower(): v for k, v in request.headers.items()}, raw)
    except (PayPalError, httpx.HTTPError):
        raise HTTPException(503, "verification unavailable")  # non-2xx -> PayPal retries

    row = WebhookEvent(paypal_event_id=event_id, event_type=event_type, raw_json=body,
                       verification=verification,
                       processed_at=datetime.now(timezone.utc) if verification == "failed" else None)
    async with db.session() as s:
        s.add(row)
        try:
            await s.commit()
        except IntegrityError:  # concurrent redelivery
            return {"ok": True, "duplicate": True}

    if verification == "failed":
        raise HTTPException(400, "signature verification failed")
    background.add_task(process_event, row.id)
    return {"ok": True}


async def process_event(row_id: int) -> None:
    async with db.session() as s:
        row = await s.get(WebhookEvent, row_id)
        if row is None or row.processed_at is not None:
            return
        try:
            res = row.raw_json.get("resource", {})
            order_id = (res.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
                        or res.get("id"))
            event = webhook_event(row.raw_json, await family_of(order_id) if order_id else None)
            if event:
                row.dedupe_key = event.dedupe_key
                await bus.publish(event)
        except Exception:
            log.exception("webhook %s failed; left unprocessed for retry", row.paypal_event_id)
            return
        row.processed_at = datetime.now(timezone.utc)
        await s.commit()


async def reprocess_pending() -> int:
    async with db.session() as s:
        ids = (await s.scalars(select(WebhookEvent.id).where(
            WebhookEvent.processed_at.is_(None), WebhookEvent.verification != "failed"))).all()
    for i in ids:
        await process_event(i)
    return len(ids)
