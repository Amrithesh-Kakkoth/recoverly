"""Persisted journey interpreter.

A run has a `cursor` (step id), `status` and `context`. It parks on a Wait (timer + event
subscription) or a Call (waits for `call.completed`). Everything that touches a run takes that
run's lock, so timers, webhooks and call completions can't interleave.

Rules (see docs/ARCHITECTURE.md section 5):
- global `on_events` interrupts apply from any step, and win over a Wait's `until_any`;
- during a live call `payment.captured` is deferred: injected into the call, never routed away;
- when a Call completes, `ctx.paid` is checked first, so a paid customer can't fall to "lost";
- `time_scale` applies only to Wait durations and `retry_after`, never to the call window."""
import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models import Customer
from app.core.config import settings
from app.core.db import db
from app.core import sse
from app.core.events import DomainEvent, EventBus, bus
from app.core.interfaces import CallManager, Channel, PayLinks
from app.journeys.dsl import Journey, Step
from app.journeys.models import JourneyRecord, JourneyRun, JourneyVersion, StepRun, Timer, TimelineEvent
from app.journeys.timeutil import next_window_start, parse_duration, utc

log = logging.getLogger(__name__)

TRIGGER_EVENTS = ("checkout.abandoned", "subscription.payment_failed")


@dataclass
class _Ctx:
    s: AsyncSession
    run: JourneyRun
    journey: Journey


class JourneyEngine:
    def __init__(self, *, channels: dict[str, Channel], call_manager: CallManager,
                 pay_links: PayLinks | None = None,
                 family_paid: Callable[[str], Awaitable[bool]] | None = None,
                 clock: Callable[[], datetime] | None = None,
                 hub: sse.SSEHub | None = None) -> None:
        self.hub = hub or sse.hub
        self.channels, self.call_manager = channels, call_manager
        self.pay_links = pay_links
        self.family_paid = family_paid or _no_family_check
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def register(self, event_bus: EventBus = bus) -> None:
        for t in TRIGGER_EVENTS:
            event_bus.subscribe(t, self.on_trigger)
        event_bus.subscribe("payment.captured", self.on_payment)
        event_bus.subscribe("call.completed", self.on_call_completed)

    # ------------------------------------------------------------------ entry points
    async def start_run(self, *, version_id: int, customer_id: str, family_id: str,
                        context: dict | None = None, time_scale: float | None = None) -> int | None:
        """None if the family already has an active run."""
        async with db.session() as s:
            version = await s.get(JourneyVersion, version_id)
            journey = Journey.model_validate(version.definition_json)
            run = JourneyRun(journey_version_id=version_id, customer_id=customer_id,
                             family_id=family_id, status="running", cursor=journey.start,
                             context_json=context or {}, attempts_json={},
                             time_scale=time_scale or settings.time_scale, started_at=self.clock())
            s.add(run)
            try:
                await s.flush()
            except IntegrityError:
                return None
            self._tl(s, run, "run.started", journey=journey.name, family_id=family_id)
            await self._commit(s)
            run_id = run.id
        await self.advance(run_id)
        return run_id

    async def advance(self, run_id: int) -> None:
        async with self._locked(run_id) as c:
            if c:
                await self._advance(c)

    async def on_trigger(self, event: DomainEvent) -> None:
        customer_id, family_id = event.payload.get("customer_id"), event.family_id
        if not (customer_id and family_id):
            return
        async with db.session() as s:
            rows = (await s.execute(
                select(JourneyVersion).join(JourneyRecord, (JourneyRecord.id == JourneyVersion.journey_id)
                                            & (JourneyRecord.active_version == JourneyVersion.version))
                .where(JourneyRecord.trigger_event == event.type))).scalars().all()
        for v in rows:
            if Journey.model_validate(v.definition_json).trigger_matches(event):
                await self.start_run(
                    version_id=v.id, customer_id=customer_id, family_id=family_id,
                    context={"amount": str(event.amount) if event.amount is not None else None,
                             "currency": event.payload.get("currency", "USD"),
                             "order_id": event.order_id})
                return

    async def on_payment(self, event: DomainEvent) -> None:
        run_id = await self._active_run_for(event.family_id)
        if run_id is None:
            return
        async with self._locked(run_id) as c:
            if c is None:
                return
            run, ctx = c.run, dict(c.run.context_json or {})
            ctx["paid"] = True
            run.context_json = ctx
            self._tl(c.s, run, "event.payment_captured", amount=str(event.amount),
                     source=event.source, status=run.status)
            step = c.journey.steps[run.cursor]
            if run.status == "in_call":
                # deferred: the voice module injects the event into the live call; we let the
                # call finish and route after completion (ctx.paid is checked first)
                await self._commit(c.s)
                return
            handler = c.journey.handler_for("payment.captured")
            if handler:
                await self._interrupt(c, handler, "payment.captured")
            elif step.type == "wait" and "payment.captured" in step.until_any and step.next:
                await self._interrupt(c, step.next, "payment.captured")
            else:
                await self._commit(c.s)

    async def on_call_completed(self, event: DomainEvent) -> None:
        run_id, call_id = event.payload.get("run_id"), event.payload.get("call_id")
        outcome = event.payload.get("outcome", "no_answer")
        if run_id is None:
            return
        async with self._locked(int(run_id)) as c:
            if c is None:
                return
            run, ctx = c.run, dict(c.run.context_json or {})
            if run.status != "in_call" or ctx.get("call_id") != call_id:
                return  # stale or duplicate completion
            ctx.update(last_outcome=outcome, leave={"outcome": outcome})
            ctx.pop("call_id", None)
            run.context_json = ctx
            self._tl(c.s, run, "call.completed", call_id=call_id, outcome=outcome)
            run.status = "running"
            if ctx.get("paid"):  # check ctx.paid before routing by outcome
                handler = c.journey.handler_for("payment.captured")
                if handler:
                    run.cursor = handler
                    await self._advance(c)
                    return
            if not await self._after_call(c, c.journey.steps[run.cursor], outcome):
                await self._advance(c)
            else:
                await self._commit(c.s)

    async def on_timer(self, timer_id: int) -> None:
        async with db.session() as s:
            t = await s.get(Timer, timer_id)
            run_id, kind, payload = (t.run_id, t.kind, dict(t.payload_json or {})) if t else (None, None, {})
        if run_id is None:
            return
        async with self._locked(run_id) as c:
            if c is None or c.run.cursor != payload.get("step_id"):
                return  # run moved on; stale timer
            run, step = c.run, c.journey.steps[c.run.cursor]
            run.status = "running"
            if kind == "wait" and step.type == "wait":
                run.context_json = {**(run.context_json or {}), "leave": {"timer": "elapsed"}}
                run.cursor = step.next
                await self._advance(c)
            elif kind in ("retry", "call_window") and step.type == "call":
                if not await self._enter_call(c, step):
                    await self._advance(c)
                else:
                    await self._commit(c.s)

    # ------------------------------------------------------------------ interpreter
    async def _advance(self, c: _Ctx) -> None:
        run, steps = c.run, c.journey.steps
        for _ in range(100):  # lint forbids unbounded loops; this is a belt-and-braces cap
            await self._close_step(c)
            step = steps[run.cursor]
            await self._open_step(c, run.cursor)
            if step.type == "message":
                await self._send_message(c, step)
                run.cursor = step.next
            elif step.type == "wait":
                delay = parse_duration(step.duration) / run.time_scale
                self._timer(c, "wait", self.clock() + delay)
                run.status = "waiting"
                self._tl(c.s, run, "wait.started", step=run.cursor, seconds=delay.total_seconds())
                break
            elif step.type == "call":
                if await self._enter_call(c, step):
                    break
            else:  # end
                await self._end(c, step)
                break
        await self._commit(c.s)

    async def _enter_call(self, c: _Ctx, step: Step) -> bool:
        """True if the run is parked (dialled or deferred); False if the cursor moved on."""
        run, ctx = c.run, dict(c.run.context_json or {})
        if ctx.get("paid") or await self.family_paid(run.family_id):  # pre-dial guard
            ctx["paid"] = True
            run.context_json = ctx
            handler = c.journey.handler_for("payment.captured")
            if handler:
                run.context_json = {**ctx, "leave": {"skipped": "already_paid"}}
                run.cursor = handler
                return False
        cust = await c.s.get(Customer, run.customer_id)
        if cust is None or cust.call_consent_at is None:
            self._tl(c.s, run, "call.skipped", reason="no_consent")
            return await self._after_call(c, step, "no_consent")
        resume = next_window_start(self.clock(), c.journey.settings.get("call_window"))
        if resume:
            self._timer(c, "call_window", resume)
            run.status = "waiting"
            self._tl(c.s, run, "call.deferred", until=resume.isoformat())
            return True
        attempts = dict(run.attempts_json or {})
        if attempts.get(run.cursor, 0) >= step.max_attempts:
            return await self._after_call(c, step, "attempts_exhausted")
        attempts[run.cursor] = attempts.get(run.cursor, 0) + 1
        run.attempts_json = attempts
        await self._commit(c.s)  # release the transaction before dialing
        call_id = await self.call_manager.start_call(str(run.id), step.model_dump())
        run.context_json = {**(run.context_json or {}), "call_id": call_id}
        run.status = "in_call"
        self._tl(c.s, run, "call.dialed", call_id=call_id, attempt=attempts[run.cursor])
        return True

    async def _after_call(self, c: _Ctx, step: Step, outcome: str) -> bool:
        """Route by outcome. True if parked on a retry timer, False if the cursor moved."""
        run = c.run
        target = step.next_by_outcome.get(outcome) or step.default or step.next
        if target == run.cursor:  # retry the same call step
            if (run.attempts_json or {}).get(run.cursor, 0) >= step.max_attempts:
                target = step.default or step.next
            else:
                delay = parse_duration(step.retry_after) / run.time_scale
                self._timer(c, "retry", self.clock() + delay)
                run.status = "waiting"
                self._tl(c.s, run, "call.retry_scheduled", seconds=delay.total_seconds())
                return True
        run.cursor = target
        return False

    async def _send_message(self, c: _Ctx, step: Step) -> None:
        await self._commit(c.s)  # never hold a DB transaction open across an external call
        run, ctx = c.run, dict(c.run.context_json or {})
        vars_: dict = {"customer_id": run.customer_id, "run_id": run.id, **{k: ctx.get(k) for k in ("amount", "currency")}}
        if step.include_pay_link and self.pay_links:
            vars_["pay_url"] = await self.pay_links.pay_link(
                run.family_id, ctx.get("amount") or "0.00", ctx.get("currency") or "USD")
        msg_id = await self.channels[step.channel].send(run.customer_id, step.template, vars_)
        self._tl(c.s, run, "message.sent", channel=step.channel, template=step.template, id=msg_id)

    async def _interrupt(self, c: _Ctx, goto: str, event_type: str) -> None:
        run = c.run
        await c.s.execute(delete(Timer).where(Timer.run_id == run.id, Timer.fired_at.is_(None)))
        run.context_json = {**(run.context_json or {}), "leave": {"interrupted_by": event_type}}
        run.cursor, run.status = goto, "running"
        await self._advance(c)

    async def _end(self, c: _Ctx, step: Step) -> None:
        run = c.run
        await c.s.execute(delete(Timer).where(Timer.run_id == run.id, Timer.fired_at.is_(None)))
        run.status, run.close_reason, run.ended_at = "done", step.result, self.clock()
        self._tl(c.s, run, "run.ended", result=step.result)
        await self._close_step(c, output={"result": step.result})

    # ------------------------------------------------------------------ persistence helpers
    @asynccontextmanager
    async def _locked(self, run_id: int):
        async with self._locks[run_id]:
            async with db.session() as s:
                run = await s.get(JourneyRun, run_id)
                if run is None or run.status == "done":
                    yield None
                    return
                version = await s.get(JourneyVersion, run.journey_version_id)
                yield _Ctx(s, run, Journey.model_validate(version.definition_json))

    async def _active_run_for(self, family_id: str | None) -> int | None:
        if not family_id:
            return None
        async with db.session() as s:
            return await s.scalar(select(JourneyRun.id).where(
                JourneyRun.family_id == family_id, JourneyRun.status != "done"))

    def _timer(self, c: _Ctx, kind: str, fire_at: datetime) -> None:
        c.s.add(Timer(run_id=c.run.id, kind=kind, fire_at=utc(fire_at),
                      payload_json={"step_id": c.run.cursor}))

    def _tl(self, s: AsyncSession, run: JourneyRun, kind: str, **payload) -> None:
        ev = TimelineEvent(run_id=run.id, kind=kind, payload_json=payload, ts=self.clock())
        s.add(ev)
        s.info.setdefault("sse", []).append(ev)

    async def _commit(self, s: AsyncSession) -> None:
        """Commit, then publish: subscribers only ever see state that is durable."""
        await s.commit()
        for ev in s.info.pop("sse", []):
            data = {"id": ev.id, "run_id": ev.run_id, "kind": ev.kind,
                    "payload": ev.payload_json, "ts": ev.ts}
            self.hub.publish(f"run:{ev.run_id}", "timeline", data)
            if ev.kind in ("run.started", "run.ended"):
                self.hub.publish("global", ev.kind, data)

    async def _open_step(self, c: _Ctx, step_id: str) -> None:
        sr = StepRun(run_id=c.run.id, step_id=step_id, status="running")
        c.s.add(sr)
        await c.s.flush()
        c.run.context_json = {**(c.run.context_json or {}), "step_run_id": sr.id}
        self._tl(c.s, c.run, "step.entered", step=step_id)

    async def _close_step(self, c: _Ctx, output: dict | None = None) -> None:
        ctx = dict(c.run.context_json or {})
        sr_id = ctx.pop("step_run_id", None)
        leave = ctx.pop("leave", None)
        if sr_id is None:
            return
        sr = await c.s.get(StepRun, sr_id)
        if sr:
            sr.status, sr.output_json = "done", output or leave
        c.run.context_json = ctx


async def _no_family_check(_: str) -> bool:
    return False
