"""Fake call manager so journeys run end to end before the real voice agent exists."""
import asyncio

from app.core.events import DomainEvent, bus


class FakeCallManager:
    def __init__(self, outcome: str = "paid", delay: float = 0.05) -> None:
        self.outcome, self.delay, self._n = outcome, delay, 0

    async def start_call(self, run_id: str, step: dict) -> str:
        self._n += 1
        call_id = f"fake-{run_id}-{self._n}"
        # Completion arrives later, from its own task: the engine holds the run lock while dialing.
        asyncio.create_task(self._complete(run_id, call_id))
        return call_id

    async def _complete(self, run_id: str, call_id: str) -> None:
        await asyncio.sleep(self.delay)
        await bus.publish(DomainEvent(type="call.completed", payload={
            "run_id": int(run_id), "call_id": call_id, "outcome": self.outcome}))
