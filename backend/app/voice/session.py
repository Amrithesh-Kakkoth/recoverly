import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class CallSession:
    """Everything about one live call. Lives in the registry from dial until completion."""

    call_id: str
    run_id: int
    family_id: str
    customer_id: str
    customer_name: str
    objective: str
    amount: Decimal
    currency: str = "USD"
    tools: list[str] = field(default_factory=list)
    offer_max_pct: float = 0.0
    max_seconds: int = 180

    transport: str = "webrtc"          # webrtc | twilio
    token: str = ""                    # per-call secret the Twilio webhook and websocket must present
    status: str = "ringing"            # ringing | live | ended
    paid: bool = False                 # set by the payment event so check_payment_status agrees
    discount_pct: float = 0.0
    hint: str | None = None            # end_call(outcome_hint)
    transfer_requested: bool = False
    ended_reason: str | None = None
    started_at: float = field(default_factory=time.monotonic)

    transcript: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    latency_ms: list[int] = field(default_factory=list)   # user-stopped -> bot-started
    results: dict[str, dict] = field(default_factory=dict)  # idempotency cache

    gate: Any = None                   # InjectionGate, set when the pipeline starts
    task: Any = None                   # PipelineTask
    done: asyncio.Event = field(default_factory=asyncio.Event)
