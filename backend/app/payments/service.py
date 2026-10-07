"""Single capture path + family guard. Nothing else in the codebase captures money."""
import asyncio
import logging
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.core.db import db
from app.core.events import DomainEvent, EventBus, bus
from app.payments.gateway import get_gateway
from app.payments.models import PaymentObject
from app.payments.normalize import capture_event, first_capture
from app.payments.paypal_rest import PayPalError, approve_url

log = logging.getLogger(__name__)
_family_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def family_of(order_id: str) -> str | None:
    async with db.session() as s:
        return await s.scalar(select(PaymentObject.family_id)
                              .where(PaymentObject.paypal_id == order_id))


async def create_order(family_id: str, amount: str, currency: str = "USD", *,
                       gateway=None) -> dict:
    gw = gateway or get_gateway()
    base = settings.public_base_url
    order = await gw.create_order(
        amount=amount, currency=currency, request_id=f"order:{uuid4()}",
        return_url=f"{base}/shop/return?family={family_id}",
        cancel_url=f"{base}/shop/cancel?family={family_id}")
    async with db.session() as s:
        s.add(PaymentObject(kind="order", paypal_id=order["id"], family_id=family_id,
                            status=order["status"], amount=Decimal(amount), currency=currency,
                            raw_json=order))
        await s.commit()
    return {"order_id": order["id"], "family_id": family_id, "approve_url": approve_url(order)}


async def capture_once(order_id: str, *, gateway=None, event_bus: EventBus | None = None) -> str:
    """Returns: captured | family_already_paid | not_completed | unknown_order.

    Under the family lock: skip if the family already has a COMPLETED capture, else capture
    with a stable PayPal-Request-Id, treat ORDER_ALREADY_CAPTURED as success (read the order),
    and count as paid only when the capture status is COMPLETED."""
    gw, event_bus = gateway or get_gateway(), event_bus or bus
    family_id = await family_of(order_id)
    if family_id is None:
        log.warning("capture_once for unknown order %s ignored", order_id)
        return "unknown_order"

    async with _family_locks[family_id]:
        async with db.session() as s:
            paid = await s.scalar(select(PaymentObject.id).where(
                PaymentObject.family_id == family_id, PaymentObject.kind == "capture",
                PaymentObject.status == "COMPLETED"))
            if paid:
                await _set_order_status(s, order_id, "SUPERSEDED")
                await s.commit()
                return "family_already_paid"

            try:
                data = await gw.capture(order_id, request_id=f"capture:{order_id}")
            except PayPalError as e:
                if not e.already_captured:
                    raise
                data = await gw.get_order(order_id)

            cap = first_capture(data)
            if cap is None or cap.get("status") != "COMPLETED":
                await _set_order_status(s, order_id, data.get("status", "UNKNOWN"))
                await s.commit()
                return "not_completed"

            existing = await s.scalar(select(PaymentObject.id)
                                      .where(PaymentObject.paypal_id == cap["id"]))
            if not existing:
                s.add(PaymentObject(kind="capture", paypal_id=cap["id"], family_id=family_id,
                                    status="COMPLETED", amount=Decimal(cap["amount"]["value"]),
                                    currency=cap["amount"]["currency_code"], raw_json=cap))
            await _set_order_status(s, order_id, "COMPLETED")
            await s.commit()

    await event_bus.publish(capture_event(order_id, cap, family_id, "capture_response"))
    return "captured"


async def _set_order_status(s, order_id: str, status: str) -> None:
    obj = await s.scalar(select(PaymentObject).where(PaymentObject.paypal_id == order_id))
    if obj:
        obj.status = status


async def on_order_approved(event: DomainEvent) -> None:
    await capture_once(event.order_id)


def register(event_bus: EventBus = bus) -> None:
    event_bus.subscribe("order.approved", on_order_approved)
