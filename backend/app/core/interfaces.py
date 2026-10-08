"""Seams between modules. Depend on these, never on another module's internals.
`CallManager` and `LiveCallRegistry` are the split-out boundary for the voice service."""
from typing import Protocol


class Channel(Protocol):
    async def send(self, customer_id: str, template: str, vars: dict) -> str: ...


class CallManager(Protocol):
    async def start_call(self, run_id: str, step: dict) -> str:
        """Dial and return call_id. Completion is reported as a `call.completed` event."""
        ...


class LiveCallRegistry(Protocol):
    async def inject(self, call_id: str, text: str) -> bool:
        """Push a verified event into a live call. False if the call is not live."""
        ...


class PaymentGateway(Protocol):
    async def create_order(self, family_id: str, amount: str, currency: str) -> dict: ...
    async def get_order(self, order_id: str) -> dict: ...
    async def capture_once(self, order_id: str) -> dict: ...


class PayLinks(Protocol):
    async def pay_link(self, family_id: str, amount: str, currency: str = "USD") -> str: ...
