"""Journey DSL: Wait, Message, Call, End. No expression language, no Branch step.
Routing is only via `next_by_outcome`; trigger filters are structured fields."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.core.events import DomainEvent


class OnEvent(BaseModel):
    event: str
    goto: str


class Step(BaseModel):
    type: Literal["wait", "message", "call", "end"]
    next: str | None = None
    next_by_outcome: dict[str, str] = {}
    default: str | None = None
    duration: str | None = None
    until_any: list[str] = []
    channel: str | None = None
    template: str | None = None
    include_pay_link: bool = False
    objective: str | None = None
    tools: list[str] = []
    offer: dict | None = None
    max_attempts: int = 1
    retry_after: str | None = None
    result: str | None = None


class Journey(BaseModel):
    name: str
    trigger: dict
    settings: dict = {}
    on_events: list[OnEvent] = []
    start: str
    steps: dict[str, Step]

    def handler_for(self, event_type: str) -> str | None:
        return next((h.goto for h in self.on_events if h.event == event_type), None)

    def trigger_matches(self, event: DomainEvent) -> bool:
        if event.type != self.trigger.get("event"):
            return False
        floor = self.trigger.get("filter", {}).get("amount_gte")
        return floor is None or (event.amount is not None and event.amount >= Decimal(str(floor)))


def edges(step: Step) -> set[str]:
    out = set(step.next_by_outcome.values())
    out.update(t for t in (step.next, step.default) if t)
    return out
