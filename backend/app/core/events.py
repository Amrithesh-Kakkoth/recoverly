"""Typed domain events and the in-process bus. The only way modules talk to each other."""
import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from decimal import Decimal

from pydantic import BaseModel


class DomainEvent(BaseModel):
    type: str  # checkout.abandoned | payment.captured | call.completed | ...
    family_id: str | None = None
    order_id: str | None = None
    capture_id: str | None = None
    amount: Decimal | None = None
    source: str = "internal"  # capture_response | webhook | simulator | internal
    payload: dict = {}

    @property
    def dedupe_key(self) -> str:
        if self.capture_id:
            return f"capture:{self.capture_id}"
        return f"{self.type}:{self.order_id or self.family_id}"


Handler = Callable[[DomainEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._seen: set[str] = set()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subs[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        key = event.dedupe_key
        if key in self._seen:
            return
        self._seen.add(key)
        await asyncio.gather(*(h(event) for h in self._subs[event.type]))


bus = EventBus()
