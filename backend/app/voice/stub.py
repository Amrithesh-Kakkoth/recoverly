"""Fake call manager so W2 journeys run end to end before the real voice agent exists."""
from app.core.events import DomainEvent, bus


class FakeCallManager:
    def __init__(self, outcome: str = "paid") -> None:
        self.outcome = outcome

    async def start_call(self, run_id: str, step: dict) -> str:
        call_id = f"fake-{run_id}"
        await bus.publish(DomainEvent(type="call.completed", payload={
            "run_id": run_id, "call_id": call_id, "outcome": self.outcome}))
        return call_id
