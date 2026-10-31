"""Read API + SSE for the dashboard and Try it. Access rules: access.py.

Snapshot-then-stream without gaps: GET /api/runs/{id} returns `last_event_id`; subscribe to
/api/stream/run:{id} with `Last-Event-ID: <that value>` and anything published in between is replayed.
Phones are never exposed here (the public board masks personal data)."""
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.accounts.models import Merchant
from app.api.access import current_merchant, optional_merchant, visible_call, visible_run
from app.api.models import Customer
from app.channels.models import Message
from app.core import sse
from app.core.db import db
from app.journeys.models import JourneyRun, TimelineEvent
from app.journeys.timeutil import utc

router = APIRouter(prefix="/api")
RUN_CHANNEL, CALL_CHANNEL = re.compile(r"^run:(\d+)$"), re.compile(r"^call:([A-Za-z0-9_-]+)$")


def _ts(dt):
    """SQLite returns naive datetimes; always send UTC with an offset so browsers don't guess."""
    return utc(dt).isoformat() if dt else None


def _message(m: Message) -> dict:
    return {"id": m.id, "run_id": m.run_id, "channel": m.channel, "body": m.body,
            "status": m.status, "created_at": _ts(m.created_at)}


def _run(r: JourneyRun, customer_name: str | None = None) -> dict:
    ctx = r.context_json or {}
    return {"id": r.id, "customer_id": r.customer_id, "family_id": r.family_id, "status": r.status,
            "customer_name": customer_name, "amount": ctx.get("amount"), "currency": ctx.get("currency"),
            "cursor": r.cursor, "close_reason": r.close_reason,
            "started_at": _ts(r.started_at), "ended_at": _ts(r.ended_at)}


@router.get("/runs")
async def list_runs(limit: int = 50, merchant: Merchant = Depends(current_merchant)) -> list[dict]:
    async with db.session() as s:
        rows = await s.execute(
            select(JourneyRun, Customer.name).outerjoin(Customer, Customer.id == JourneyRun.customer_id)
            .where(JourneyRun.merchant_id == merchant.id)
            .order_by(JourneyRun.id.desc()).limit(min(limit, 200)))
        return [_run(r, name) for r, name in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: int, request: Request, family: str | None = None) -> dict:
    run = await visible_run(run_id, request, family)
    async with db.session() as s:
        customer = await s.get(Customer, run.customer_id)
        timeline = (await s.scalars(select(TimelineEvent).where(
            TimelineEvent.run_id == run_id).order_by(TimelineEvent.id))).all()
        messages = (await s.scalars(select(Message).where(
            Message.run_id == run_id).order_by(Message.id))).all()
    return {**_run(run, customer.name if customer else None),
            "timeline": [{"id": e.id, "kind": e.kind, "payload": e.payload_json, "ts": _ts(e.ts)}
                         for e in timeline],
            "messages": [_message(m) for m in messages],
            "last_event_id": sse.hub.latest_id(f"run:{run_id}")}


@router.get("/customers/{customer_id}/messages")
async def customer_messages(customer_id: str, merchant: Merchant = Depends(current_merchant)) -> list[dict]:
    async with db.session() as s:
        customer = await s.get(Customer, customer_id)
        if customer is None or customer.merchant_id != merchant.id:
            raise HTTPException(404, "customer not found")
        rows = await s.scalars(select(Message).where(
            Message.customer_id == customer_id).order_by(Message.id))
        return [_message(m) for m in rows]


async def events(channel: str, last_id: int | None) -> AsyncIterator[dict]:
    async for item in sse.hub.subscribe(channel, last_id):
        yield {**item, "id": str(item["id"])}  # sse-starlette only encodes string ids


@router.get("/stream/{channel}")
async def stream(channel: str, request: Request, last_event_id: str | None = Header(default=None),
                 since: str | None = None, family: str | None = None):
    """Resume point: `Last-Event-ID` header, or `?since=` for EventSource (no custom headers).
    `?since=0` replays the whole buffer. Channels: `merchant` (your runs starting and ending),
    `run:{id}`, `call:{id}`. The internal `global` channel is never served."""
    if channel == "merchant":
        merchant = await optional_merchant(request)
        if merchant is None:
            raise HTTPException(401, "sign in required")
        channel = f"merchant:{merchant.id}"
    elif m := RUN_CHANNEL.match(channel):
        await visible_run(int(m[1]), request, family)
    elif m := CALL_CHANNEL.match(channel):
        await visible_call(m[1], request, family)
    else:
        raise HTTPException(404, "unknown channel")
    raw = last_event_id if last_event_id is not None else since
    last = int(raw) if raw and raw.isdigit() else None
    return EventSourceResponse(events(channel, last), ping=15)
