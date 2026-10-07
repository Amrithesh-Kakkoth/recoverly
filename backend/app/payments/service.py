"""Single capture path + family guard. Nothing else in the codebase captures money."""
from app.core.events import DomainEvent, bus


async def capture_once(order_id: str) -> None:
    # TODO W1-B: run lock -> family already paid? skip -> REST capture with
    # PayPal-Request-Id capture:{order_id} -> 422 ORDER_ALREADY_CAPTURED is success
    # -> only COMPLETED counts -> publish payment.captured
    raise NotImplementedError
    await bus.publish(DomainEvent(type="payment.captured", order_id=order_id))  # noqa: unreachable
