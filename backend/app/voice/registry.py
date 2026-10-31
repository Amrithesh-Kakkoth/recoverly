"""Live call registry: call_id -> CallSession, in memory. Possible because everything runs in one
process; this class is the seam to replace with HTTP/Redis if `voice` is ever split out.

Subscribed to payment.captured: sets `session.paid` (so check_payment_status agrees) and injects
the verified event into the call, queued by the gate if the moment is busy."""
import logging

from app.core.events import DomainEvent, EventBus, bus
from app.voice.prompt import payment_event_text
from app.voice.session import CallSession

log = logging.getLogger(__name__)


class LiveCalls:
    def __init__(self) -> None:
        self._by_call: dict[str, CallSession] = {}

    def register(self, session: CallSession) -> None:
        self._by_call[session.call_id] = session

    def unregister(self, call_id: str) -> None:
        self._by_call.pop(call_id, None)

    def get(self, call_id: str) -> CallSession | None:
        return self._by_call.get(call_id)

    def by_family(self, family_id: str | None) -> CallSession | None:
        return next((s for s in self._by_call.values() if s.family_id == family_id), None)

    def count(self) -> int:
        return len(self._by_call)

    async def inject(self, call_id: str, text: str) -> bool:
        s = self._by_call.get(call_id)
        if s is None or s.gate is None:
            return False
        await s.gate.inject(text)
        return True

    async def on_payment(self, event: DomainEvent) -> None:
        s = self.by_family(event.family_id)
        if s is None or s.status == "ended":
            return
        s.paid = True
        if s.gate is not None:
            await s.gate.inject(payment_event_text(event.amount, s.currency))

    def register_bus(self, event_bus: EventBus = bus) -> None:
        event_bus.subscribe("payment.captured", self.on_payment)
