"""Journey DSL: Wait, Message, Call, End. Routing only via next_by_outcome."""
from typing import Literal

from pydantic import BaseModel


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
    on_events: list[dict] = []
    start: str
    steps: dict[str, Step]
