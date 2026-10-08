"""DB-polled timer loop. Timers live in Postgres, so they survive restarts: anything due when
the process comes back up fires on the first tick."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.core.db import db
from app.journeys.engine import JourneyEngine
from app.journeys.models import Timer
from app.journeys.timeutil import utc

log = logging.getLogger(__name__)


class TimerLoop:
    def __init__(self, engine: JourneyEngine, poll_seconds: float = 1.0) -> None:
        self.engine, self.poll = engine, poll_seconds
        self._stop = asyncio.Event()

    async def tick(self, now: datetime | None = None) -> int:
        """Fire everything due. Each timer is claimed atomically (fired_at IS NULL) so two
        loops can't double-fire it. Returns how many fired."""
        now = utc(now or self.engine.clock())  # naive-UTC storage: always compare in UTC
        async with db.session() as s:
            due = (await s.scalars(select(Timer.id).where(
                Timer.fired_at.is_(None), Timer.fire_at <= now).order_by(Timer.fire_at))).all()
        fired = 0
        for timer_id in due:
            async with db.session() as s:
                res = await s.execute(update(Timer).where(
                    Timer.id == timer_id, Timer.fired_at.is_(None)).values(fired_at=now))
                await s.commit()
            if res.rowcount != 1:
                continue
            fired += 1
            try:
                await self.engine.on_timer(timer_id)
            except Exception:
                log.exception("timer %s handler failed", timer_id)
        return fired

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick(datetime.now(timezone.utc))
            except Exception:
                log.exception("timer tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), self.poll)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
