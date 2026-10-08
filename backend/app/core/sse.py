"""In-process SSE hub. Channels: `run:{id}`, `call:{id}`, `global`.

Each channel keeps a short replay buffer so a client that reconnects (or fetches a snapshot
and then subscribes) can pass its last event id and miss nothing."""
import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import datetime
from itertools import count


def _default(o):
    return o.isoformat() if isinstance(o, datetime) else str(o)


class SSEHub:
    def __init__(self, backlog: int = 200) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._log: dict[str, deque] = defaultdict(lambda: deque(maxlen=backlog))
        self._seq = count(1)  # ids are global and increasing, so they order across channels

    def publish(self, channel: str, event: str, data: dict) -> int:
        item = {"id": next(self._seq), "event": event, "data": json.dumps(data, default=_default)}
        self._log[channel].append(item)
        for q in self._subs[channel]:
            q.put_nowait(item)
        return item["id"]

    def latest_id(self, channel: str) -> int:
        log = self._log.get(channel)
        return log[-1]["id"] if log else 0

    async def subscribe(self, channel: str, last_id: int | None = None) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[channel].add(q)  # register first so nothing published during replay is lost
        try:
            seen = last_id or 0
            for item in [i for i in self._log.get(channel, ()) if i["id"] > seen]:
                seen = item["id"]
                yield item
            while True:
                item = await q.get()
                if item["id"] > seen:
                    seen = item["id"]
                    yield item
        finally:
            self._subs[channel].discard(q)
            if not self._subs[channel]:
                del self._subs[channel]


hub = SSEHub()  # consumers read `sse.hub` at use time so tests can swap it
