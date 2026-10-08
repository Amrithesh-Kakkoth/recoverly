"""Injection gate: when may a verified PayPal event be pushed into the LLM context?

Busy (-> queue) if the user is speaking, the bot is speaking, or a function call is pending.
Flush on UserStoppedSpeaking / bot turn end / FunctionCallResult. Free -> push immediately with
run_llm=True so the agent reacts at once. Pure logic; GateProcessor in pipeline.py feeds it frames."""
import time
from collections.abc import Awaitable, Callable

Push = Callable[[list[dict]], Awaitable[None]]


class InjectionGate:
    def __init__(self, push: Push) -> None:
        self._push = push
        self.user_speaking = False
        self.bot_speaking = False
        self.pending_calls: set[str] = set()
        self._queue: list[str] = []
        self._user_stopped_at: float | None = None
        self.latencies_ms: list[int] = []

    @property
    def busy(self) -> bool:
        return self.user_speaking or self.bot_speaking or bool(self.pending_calls)

    @property
    def queued(self) -> int:
        return len(self._queue)

    async def inject(self, text: str) -> bool:
        """True if pushed now, False if queued behind a busy moment."""
        self._queue.append(text)
        if self.busy:
            return False
        await self._flush()
        return True

    async def _flush(self) -> None:
        if not self._queue or self.busy:
            return
        texts, self._queue = self._queue, []
        await self._push([{"role": "system", "content": t} for t in texts])

    # -- frame hooks (called by the pipeline processor) --------------------------------
    async def user_started(self) -> None:
        self.user_speaking = True

    async def user_stopped(self) -> None:
        self.user_speaking = False
        self._user_stopped_at = time.monotonic()
        await self._flush()

    async def bot_started(self) -> None:
        self.bot_speaking = True
        if self._user_stopped_at is not None:  # voice-to-voice latency for the UI
            self.latencies_ms.append(int((time.monotonic() - self._user_stopped_at) * 1000))
            self._user_stopped_at = None

    async def bot_stopped(self) -> None:
        self.bot_speaking = False
        await self._flush()

    async def call_started(self, call_id: str) -> None:
        self.pending_calls.add(call_id)

    async def call_finished(self, call_id: str) -> None:
        self.pending_calls.discard(call_id)
        await self._flush()
