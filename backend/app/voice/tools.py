"""The agent's four tools. Every limit lives here, in the handler, never in the prompt: the LLM
can ask for anything and still can't exceed the merchant's discount, duplicate an order, or learn
that a payment happened from anything but our own facts. Results are built by us (never PayPal's
or the toolkit's `message`). Idempotent per `{call_id}:{tool}:{hash(args)}`."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from app.voice.session import CallSession

ORDER_REUSE_MAX_AGE = timedelta(hours=2, minutes=30)   # PayPal orders expire at 3 h
ORDER_LIFETIME = timedelta(hours=3)
IDEMPOTENT = {"send_payment_link", "apply_offer"}  # mutating tools; reads must stay live

TOOL_SPECS = {
    "send_payment_link": {
        "description": "Send the customer a PayPal payment link on WhatsApp. Optionally apply a "
                       "discount percentage you are allowed to offer.",
        "properties": {"offer_pct": {"type": "number", "description": "Discount percent, optional."}},
        "required": []},
    "check_payment_status": {
        "description": "Check whether the customer has paid yet. Returns unpaid, approved or paid.",
        "properties": {}, "required": []},
    "apply_offer": {
        "description": "Apply a discount percentage to the order. Only within the allowed maximum.",
        "properties": {"pct": {"type": "number", "description": "Discount percent."}},
        "required": ["pct"]},
    "end_call": {
        "description": "End the call politely once the conversation is finished.",
        "properties": {"outcome_hint": {
            "type": "string",
            "enum": ["paid", "promised_to_pay", "declined", "callback_requested", "needs_human"]}},
        "required": ["outcome_hint"]},
    "transfer_to_human": {
        "description": "Ask for a human colleague to follow up. Use when the customer asks for one.",
        "properties": {}, "required": []},
}


class VoiceDeps(Protocol):
    def now(self) -> datetime: ...
    async def open_order(self, family_id: str) -> dict | None:
        """Latest unpaid order in the family: {order_id, amount: Decimal, created_at}."""
    async def create_order(self, family_id: str, amount: str, currency: str) -> dict:
        """-> {order_id, approve_url}"""
    async def order_status(self, order_id: str) -> str: ...
    async def family_paid(self, family_id: str) -> bool: ...
    async def deliver(self, session: CallSession, template: str, vars: dict) -> None: ...


def money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class ToolBox:
    def __init__(self, session: CallSession, deps: VoiceDeps) -> None:
        self.s, self.deps = session, deps

    async def dispatch(self, name: str, args: dict | None) -> dict:
        args = args or {}
        if name not in self.s.tools:
            return {"ok": False, "error": "tool_not_allowed"}
        key = f"{self.s.call_id}:{name}:{hashlib.sha1(json.dumps(args, sort_keys=True).encode()).hexdigest()[:12]}"
        if name in IDEMPOTENT and key in self.s.results:  # LLM retried: same answer, no 2nd order
            return self.s.results[key]
        try:
            result = await getattr(self, name)(**args)
        except TypeError:
            result = {"ok": False, "error": "bad_arguments"}
        except Exception:
            result = {"ok": False, "error": "internal_error"}
        if name in IDEMPOTENT:
            self.s.results[key] = result
        self.s.tool_calls.append({"tool": name, "args": args, "result": result,
                                  "at": self.deps.now().isoformat()})
        return result

    # -- helpers ------------------------------------------------------------------------
    def _price(self, pct: float) -> Decimal:
        return money(self.s.amount * (Decimal(1) - Decimal(str(pct)) / 100))

    def _pct_ok(self, pct: float) -> bool:
        return 0 <= pct <= self.s.offer_max_pct

    async def _paid(self) -> bool:
        if self.s.paid:
            return True
        if await self.deps.family_paid(self.s.family_id):
            self.s.paid = True
        return self.s.paid

    # -- tools --------------------------------------------------------------------------
    async def send_payment_link(self, offer_pct: float | None = None) -> dict:
        if await self._paid():
            return {"ok": False, "error": "already_paid"}
        pct = self.s.discount_pct if offer_pct is None else float(offer_pct)
        if not self._pct_ok(pct):
            return {"ok": False, "error": "offer_exceeds_limit", "max_pct": self.s.offer_max_pct}
        self.s.discount_pct = max(self.s.discount_pct, pct)
        amount = self._price(self.s.discount_pct)
        now = self.deps.now()
        order = await self.deps.open_order(self.s.family_id)
        fresh = (order and order["amount"] == amount
                 and now - order["created_at"] < ORDER_REUSE_MAX_AGE)
        if fresh:
            created, order_id = order["created_at"], order["order_id"]
            url = order.get("approve_url")
        else:
            made = await self.deps.create_order(self.s.family_id, str(amount), self.s.currency)
            created, order_id, url = now, made["order_id"], made["approve_url"]
        if url:
            await self.deps.deliver(self.s, "pay_link", {
                "pay_url": url, "amount": str(amount), "currency": self.s.currency,
                "run_id": self.s.run_id})
        left = max(0, int((created + ORDER_LIFETIME - now).total_seconds() // 60))
        return {"ok": True, "amount": str(amount), "expires_in_min": left, "order_id": order_id}

    async def apply_offer(self, pct: float) -> dict:
        if await self._paid():
            return {"ok": False, "error": "already_paid"}
        pct = float(pct)
        if not self._pct_ok(pct):
            return {"ok": False, "error": "offer_exceeds_limit", "max_pct": self.s.offer_max_pct}
        self.s.discount_pct = max(self.s.discount_pct, pct)
        amount = self._price(self.s.discount_pct)
        await self.deps.create_order(self.s.family_id, str(amount), self.s.currency)  # same family
        return {"ok": True, "new_amount": str(amount)}

    async def check_payment_status(self) -> dict:
        if await self._paid():
            return {"status": "paid", "amount": str(self._price(self.s.discount_pct))}
        order = await self.deps.open_order(self.s.family_id)
        if order and await self.deps.order_status(order["order_id"]) == "APPROVED":
            return {"status": "approved"}
        return {"status": "unpaid"}

    async def end_call(self, outcome_hint: str = "declined") -> dict:
        self.s.hint = outcome_hint
        self.s.ended_reason = self.s.ended_reason or "agent_ended"
        return {}

    async def transfer_to_human(self) -> dict:
        self.s.transfer_requested = True  # log only; no real transfer
        return {"ok": True}


class PaymentDeps:
    """Real wiring: payments module + channels."""

    def __init__(self, channels: dict) -> None:
        self.channels = channels

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def open_order(self, family_id: str) -> dict | None:
        from sqlalchemy import select

        from app.core.db import db
        from app.journeys.timeutil import utc
        from app.payments.models import PaymentObject
        async with db.session() as s:
            o = await s.scalar(select(PaymentObject).where(
                PaymentObject.family_id == family_id, PaymentObject.kind == "order",
                PaymentObject.status.in_(["CREATED", "PAYER_ACTION_REQUIRED", "APPROVED"]))
                .order_by(PaymentObject.id.desc()))
        if o is None:
            return None
        from app.payments.paypal_rest import approve_url
        return {"order_id": o.paypal_id, "amount": money(o.amount), "created_at": utc(o.created_at),
                "approve_url": approve_url(o.raw_json or {})}

    async def create_order(self, family_id: str, amount: str, currency: str) -> dict:
        from app.payments.service import create_order
        return await create_order(family_id, amount, currency)

    async def order_status(self, order_id: str) -> str:
        from app.payments.gateway import get_gateway
        return (await get_gateway().get_order(order_id)).get("status", "UNKNOWN")

    async def family_paid(self, family_id: str) -> bool:
        from app.payments.service import family_is_paid
        return await family_is_paid(family_id)

    async def deliver(self, session: CallSession, template: str, vars: dict) -> None:
        for ch in ("whatsapp", "web_inbox"):
            if ch in self.channels:
                await self.channels[ch].send(session.customer_id, template, vars)
