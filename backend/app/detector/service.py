"""Abandon detector. On order creation a check is scheduled (15 min; 90 s in the demo, real
time: time_scale never applies here). When it fires we GET the order:

  CREATED / PAYER_ACTION_REQUIRED -> emit checkout.abandoned
  APPROVED but uncaptured         -> capture_once (they paid; don't nag them)
  COMPLETED / VOIDED / family paid -> nothing"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import db
from app.core.events import DomainEvent, EventBus, bus
from app.detector.models import AbandonCheck
from app.journeys.timeutil import utc
from app.payments.gateway import get_gateway
from app.payments.service import capture_once, family_is_paid

log = logging.getLogger(__name__)
UNPAID = {"CREATED", "PAYER_ACTION_REQUIRED"}
MAX_ATTEMPTS, RETRY_SECONDS = 3, 30


async def schedule(*, order_id: str, family_id: str, customer_id: str, amount: str,
                   currency: str = "USD", delay_seconds: float | None = None,
                   now: datetime | None = None) -> None:
    delay = settings.abandon_after_seconds if delay_seconds is None else delay_seconds
    fire_at = utc(now or datetime.now(timezone.utc)) + timedelta(seconds=delay)
    async with db.session() as s:
        s.add(AbandonCheck(order_id=order_id, family_id=family_id, customer_id=customer_id,
                           amount=Decimal(amount), currency=currency, fire_at=fire_at))
        await s.commit()


class AbandonDetector:
    def __init__(self, *, event_bus: EventBus = bus, gateway=None,
                 capture: Callable[[str], Awaitable[str]] = capture_once,
                 family_paid: Callable[[str], Awaitable[bool]] = family_is_paid,
                 clock: Callable[[], datetime] | None = None, poll_seconds: float = 1.0) -> None:
        self.bus, self._gateway, self.capture, self.family_paid = event_bus, gateway, capture, family_paid
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll = poll_seconds
        self._stop = asyncio.Event()

    async def tick(self) -> int:
        """Run every due check once. Each is claimed atomically so loops can't double-fire."""
        now = utc(self.clock())
        async with db.session() as s:
            due = (await s.scalars(select(AbandonCheck.id).where(
                AbandonCheck.fired_at.is_(None), AbandonCheck.fire_at <= now)
                .order_by(AbandonCheck.fire_at))).all()
        handled = 0
        for check_id in due:
            async with db.session() as s:
                claimed = await s.execute(update(AbandonCheck).where(
                    AbandonCheck.id == check_id, AbandonCheck.fired_at.is_(None))
                    .values(fired_at=now))
                await s.commit()
            if claimed.rowcount == 1:
                handled += 1
                await self._check(check_id, now)
        return handled

    async def _check(self, check_id: int, now: datetime) -> None:
        async with db.session() as s:
            check = await s.get(AbandonCheck, check_id)
        try:
            result = await self._decide(check)
        except Exception:
            log.exception("abandon check for %s failed", check.order_id)
            await self._retry_or_give_up(check_id, now)
            return
        async with db.session() as s:
            (await s.get(AbandonCheck, check_id)).result = result
            await s.commit()

    async def _decide(self, check: AbandonCheck) -> str:
        if await self.family_paid(check.family_id):
            return "paid"
        order = await (self._gateway or get_gateway()).get_order(check.order_id)
        status = order.get("status")
        if status in UNPAID:
            await self.bus.publish(DomainEvent(
                type="checkout.abandoned", family_id=check.family_id, order_id=check.order_id,
                amount=check.amount, payload={"customer_id": check.customer_id,
                                              "currency": check.currency}))
            return "abandoned"
        if status == "APPROVED":
            await self.capture(check.order_id)
            return "captured"
        return "paid" if status == "COMPLETED" else "closed"

    async def _retry_or_give_up(self, check_id: int, now: datetime) -> None:
        async with db.session() as s:
            check = await s.get(AbandonCheck, check_id)
            check.attempts += 1
            if check.attempts < MAX_ATTEMPTS:
                check.fired_at, check.fire_at = None, now + timedelta(seconds=RETRY_SECONDS)
            else:
                check.result = "error"
            await s.commit()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("abandon tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), self.poll)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
