"""One normalizer for webhook bodies and capture responses, so both produce the same
DomainEvent and the same dedupe key (`capture:{capture_id}`)."""
from decimal import Decimal

from app.core.events import DomainEvent


def first_capture(order: dict) -> dict | None:
    for pu in order.get("purchase_units", []):
        caps = pu.get("payments", {}).get("captures", [])
        if caps:
            return caps[0]
    return None


def capture_event(order_id: str, capture: dict, family_id: str | None, source: str) -> DomainEvent:
    return DomainEvent(
        type="payment.captured", family_id=family_id, order_id=order_id,
        capture_id=capture["id"], amount=Decimal(capture["amount"]["value"]), source=source)


def webhook_event(body: dict, family_id: str | None) -> DomainEvent | None:
    """None = a type we store but don't act on."""
    kind, res = body.get("event_type"), body.get("resource", {})
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        order_id = res.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        return DomainEvent(
            type="payment.captured", family_id=family_id, order_id=order_id,
            capture_id=res["id"], amount=Decimal(res["amount"]["value"]), source="webhook")
    if kind == "CHECKOUT.ORDER.APPROVED":
        return DomainEvent(type="order.approved", family_id=family_id, order_id=res["id"],
                           source="webhook")
    return None
