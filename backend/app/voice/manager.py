"""CallManager implementation. Dial = create a `ringing` session and tell the dashboard (the judge's
browser then 'answers' over WebRTC). Completion is always reported later, from its own task, via
`call.completed` on the bus: the journey engine holds the run lock while dialing, so it must never
be published synchronously from start_call.

Spend caps: kill switch, max concurrent calls, ring timeout, hard per-call time cap."""
import asyncio
import hmac
import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

from sqlalchemy import select

from app.accounts.models import Merchant
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
PhoneRunner = Callable[[CallSession, object, object, VoiceDeps], Awaitable[None]]  # session, ws, serializer, deps


async def mark_interrupted_calls() -> int:
    """Boot recovery for the `calls` table: anything not `ended` was cut off by a restart."""
    from sqlalchemy import update
    async with db.session() as s:
        res = await s.execute(update(Call).where(Call.status != "ended").values(status="interrupted"))
        await s.commit()
        return res.rowcount or 0


class VoiceCallManager:
    def __init__(self, *, live: LiveCalls, deps: VoiceDeps, classify: Classifier | None,
                 bot_runner: BotRunner, phone_runner: PhoneRunner | None = None, dialer=None,
                 request_handler=None, event_bus: EventBus = bus,
                 hub: sse.SSEHub | None = None, cfg: Settings = default_settings) -> None:
        self.live, self.deps, self.classify, self.bot_runner = live, deps, classify, bot_runner
        self.phone_runner, self.dialer = phone_runner, dialer
        self.handler, self.bus, self.cfg = request_handler, event_bus, cfg
        self.hub = hub or sse.hub
        self._timers: dict[str, list[asyncio.Task]] = {}
        self._bots: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------ CallManager
    async def start_call(self, run_id: str, step: dict) -> str:
        async with db.session() as s:
            run = await s.get(JourneyRun, int(run_id))
            cust = await s.get(Customer, run.customer_id)
            merchant = await s.get(Merchant, run.merchant_id) if run.merchant_id else None
        ctx = run.context_json or {}
        sess = CallSession(
            call_id=f"call_{uuid.uuid4().hex[:10]}", run_id=run.id, family_id=run.family_id,
            customer_id=run.customer_id, customer_name=(cust.name if cust else "there"),
            merchant_name=merchant.store_name if merchant else "",
            objective=step.get("objective") or "Help the customer complete the purchase",
            amount=Decimal(ctx.get("amount") or "0.00"), currency=ctx.get("currency") or "USD",
            tools=list(step.get("tools") or []),
            offer_max_pct=float((step.get("offer") or {}).get("max", 0)),
            max_seconds=self.cfg.call_max_seconds)
        phone = self.cfg.phone_enabled and bool(cust and cust.phone_e164)
        if phone:
            sess.transport, sess.token = "twilio", secrets.token_urlsafe(16)
        async with db.session() as s:
            s.add(Call(id=sess.call_id, run_id=run.id, transport=sess.transport, status="ringing"))
            await s.commit()

        if self.cfg.kill_switch or self.live.count() >= self.cfg.max_concurrent_calls:
            self._later(self.finish(sess, no_answer=True, reason="busy"))
            return sess.call_id
        self.live.register(sess)
        self._timers[sess.call_id] = [asyncio.create_task(self._ring_timeout(sess))]
        if phone:
            try:
                sid = await self._dialer().dial(cust.phone_e164, sess.call_id, sess.token)
            except Exception:
                log.exception("dialing %s failed", sess.call_id)
                self._later(self.finish(sess, no_answer=True, reason="dial_failed"))
                return sess.call_id
            async with db.session() as s:
                (await s.get(Call, sess.call_id)).twilio_sid = sid
                await s.commit()
        else:  # the dashboard's "Answer" button rings in the browser
            self.hub.publish(f"run:{run.id}", "call.ringing", {"call_id": sess.call_id, "run_id": run.id})
        return sess.call_id

    def _dialer(self):
        if self.dialer is None:
            from app.voice.phone import TwilioDialer
            self.dialer = TwilioDialer(self.cfg)
        return self.dialer

    # ------------------------------------------------------------------ real phone call
    async def answer_phone(self, call_id: str, token: str, websocket, stream_sid: str, call_sid: str) -> None:
        """Twilio's media stream for a call the customer just picked up; runs the agent until it ends."""
        sess = self.live.get(call_id)
        if sess is None or sess.status == "ended" or not hmac.compare_digest(sess.token or "-", token):
            raise LookupError("call not found")
        if sess.status != "ringing":
            raise ValueError("call already answered")
        sess.status = "live"
        for t in self._timers.pop(call_id, []):
            t.cancel()
        self._timers[call_id] = [asyncio.create_task(self._time_cap(sess))]
        from pipecat.serializers.twilio import TwilioFrameSerializer
        serializer = TwilioFrameSerializer(stream_sid, call_sid, self.cfg.twilio_account_sid,
                                           self.cfg.twilio_auth_token)
        runner = self.phone_runner
        if runner is None:
            from app.voice.pipeline import run_phone_bot
            runner = run_phone_bot
        try:
            await runner(sess, websocket, serializer, self.deps)
        except Exception:
            log.exception("phone bot for %s crashed", call_id)
            sess.ended_reason = "error"
        finally:
            await self.finish(sess)

    async def on_phone_status(self, call_id: str, status: str) -> None:
        """Twilio's final status: a call nobody picked up never opens a media stream."""
        from app.voice.phone import DEAD_STATUSES
        sess = self.live.get(call_id)
        if sess is not None and sess.status == "ringing" and status in DEAD_STATUSES:
            await self.finish(sess, no_answer=True, reason=status)

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

        # tools only run mid-conversation, so a call that used any was answered even if the
        # transcript came back empty
        spoke = any(m["role"] == "user" for m in sess.transcript) or bool(sess.tool_calls)
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
