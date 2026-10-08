"""CallManager implementation. Dial = create a `ringing` session and tell the dashboard (the judge's
browser then 'answers' over WebRTC). Completion is always reported later, from its own task, via
`call.completed` on the bus: the journey engine holds the run lock while dialing, so it must never
be published synchronously from start_call.

Spend caps: kill switch, max concurrent calls, ring timeout, hard per-call time cap."""
import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

from sqlalchemy import select

from app.api.models import Customer
from app.core import sse
from app.core.config import Settings, settings as default_settings
from app.core.db import db
from app.core.events import DomainEvent, EventBus, bus
from app.journeys.models import JourneyRun
from app.voice.models import Call, Outcome
from app.voice.registry import LiveCalls
from app.voice.session import CallSession
from app.voice.tagger import Classifier, tag_outcome
from app.voice.tools import VoiceDeps

log = logging.getLogger(__name__)
BotRunner = Callable[[CallSession, object, VoiceDeps], Awaitable[None]]


class VoiceCallManager:
    def __init__(self, *, live: LiveCalls, deps: VoiceDeps, classify: Classifier | None,
                 bot_runner: BotRunner, request_handler=None, event_bus: EventBus = bus,
                 hub: sse.SSEHub | None = None, cfg: Settings = default_settings) -> None:
        self.live, self.deps, self.classify, self.bot_runner = live, deps, classify, bot_runner
        self.handler, self.bus, self.cfg = request_handler, event_bus, cfg
        self.hub = hub or sse.hub
        self._timers: dict[str, list[asyncio.Task]] = {}
        self._bots: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------ CallManager
    async def start_call(self, run_id: str, step: dict) -> str:
        async with db.session() as s:
            run = await s.get(JourneyRun, int(run_id))
            cust = await s.get(Customer, run.customer_id)
        ctx = run.context_json or {}
        sess = CallSession(
            call_id=f"call_{uuid.uuid4().hex[:10]}", run_id=run.id, family_id=run.family_id,
            customer_id=run.customer_id, customer_name=(cust.name if cust else "there"),
            objective=step.get("objective") or "Help the customer complete the purchase",
            amount=Decimal(ctx.get("amount") or "0.00"), currency=ctx.get("currency") or "USD",
            tools=list(step.get("tools") or []),
            offer_max_pct=float((step.get("offer") or {}).get("max", 0)),
            max_seconds=self.cfg.call_max_seconds)
        async with db.session() as s:
            s.add(Call(id=sess.call_id, run_id=run.id, transport="webrtc", status="ringing"))
            await s.commit()

        if self.cfg.kill_switch or self.live.count() >= self.cfg.max_concurrent_calls:
            self._later(self.finish(sess, no_answer=True, reason="busy"))
            return sess.call_id
        self.live.register(sess)
        self.hub.publish(f"run:{run.id}", "call.ringing", {"call_id": sess.call_id,
                                                           "run_id": run.id})
        self._timers[sess.call_id] = [asyncio.create_task(self._ring_timeout(sess))]
        return sess.call_id

    # ------------------------------------------------------------------ answering
    async def answer(self, call_id: str, request) -> dict | None:
        """Browser WebRTC offer for a ringing call; returns the SDP answer."""
        sess = self.live.get(call_id)
        if sess is None or sess.status == "ended":
            raise LookupError("call not found")
        if sess.status != "ringing":
            raise ValueError("call already answered")
        sess.status = "live"
        for t in self._timers.pop(call_id, []):
            t.cancel()
        self._timers[call_id] = [asyncio.create_task(self._time_cap(sess))]

        async def on_connection(conn) -> None:
            self._bots[call_id] = asyncio.create_task(self._run(sess, conn))

        try:
            return await self._request_handler().handle_web_request(request, on_connection)
        except Exception:
            sess.status = "ringing"  # failed negotiation: let the judge retry until it times out
            raise

    def _request_handler(self):
        if self.handler is None:
            from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler

            from app.voice.pipeline import ice_servers
            self.handler = SmallWebRTCRequestHandler(ice_servers=ice_servers(self.cfg))
        return self.handler

    async def _run(self, sess: CallSession, conn) -> None:
        try:
            await self.bot_runner(sess, conn, self.deps)
        except Exception:
            log.exception("bot for %s crashed", sess.call_id)
            sess.ended_reason = "error"
        finally:
            await self.finish(sess)

    # ------------------------------------------------------------------ timers
    async def _ring_timeout(self, sess: CallSession) -> None:
        await asyncio.sleep(self.cfg.ring_timeout_seconds)
        if sess.status == "ringing":
            await self.finish(sess, no_answer=True, reason="ring_timeout")

    async def _time_cap(self, sess: CallSession) -> None:
        await asyncio.sleep(sess.max_seconds)
        sess.ended_reason = "time_cap"
        if sess.task is not None:
            await sess.task.cancel()
        else:
            await self.finish(sess)

    def _later(self, coro) -> None:
        asyncio.create_task(self._delayed(coro))

    @staticmethod
    async def _delayed(coro) -> None:
        await asyncio.sleep(0)  # let start_call return and the engine release the run lock first
        await coro

    # ------------------------------------------------------------------ completion
    async def finish(self, sess: CallSession, *, no_answer: bool = False,
                     reason: str | None = None) -> None:
        """Idempotent: tag the outcome, persist, release, and report call.completed."""
        if sess.status == "ended" and sess.done.is_set():
            return
        sess.status = "ended"
        sess.ended_reason = sess.ended_reason or reason or "ended"
        sess.done.set()
        me = asyncio.current_task()
        for t in self._timers.pop(sess.call_id, []):
            if t is not me:  # a timer that triggered this finish must not cancel itself mid-way
                t.cancel()
        self._bots.pop(sess.call_id, None)
        self.live.unregister(sess.call_id)

        spoke = any(m["role"] == "user" for m in sess.transcript)
        paid = sess.paid or await self.deps.family_paid(sess.family_id)
        tagged = await tag_outcome(
            transcript=sess.transcript, hint=sess.hint, family_paid=paid,
            no_answer=no_answer or not (spoke or paid), transfer_requested=sess.transfer_requested,
            classify=self.classify, service_error=sess.ended_reason == "service_error")

        data = {"call_id": sess.call_id, "run_id": sess.run_id, "outcome": tagged.label,
                "summary": tagged.summary, "overridden_by": tagged.overridden_by,
                "ended_reason": sess.ended_reason}
        try:
            async with db.session() as s:
                call = await s.get(Call, sess.call_id)
                call.status, call.transcript_json = "ended", sess.transcript
                call.tool_calls_json = sess.tool_calls
                call.latency_json = {"voice_to_voice_ms": sess.latency_ms}
                s.add(Outcome(call_id=sess.call_id, label=tagged.label, confidence=tagged.confidence,
                              summary=tagged.summary, overridden_by=tagged.overridden_by))
                await s.commit()
            self.hub.publish(f"run:{sess.run_id}", "call.ended", data)
            self.hub.publish(f"call:{sess.call_id}", "call.ended", data)
        except Exception:
            log.exception("persisting call %s failed", sess.call_id)
        # Always report completion: the journey run is parked on it and would hang forever.
        await self.bus.publish(DomainEvent(type="call.completed", payload={
            "run_id": sess.run_id, "call_id": sess.call_id, "outcome": tagged.label}))
