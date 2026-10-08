"""Read API + SSE for the dashboard and the judge's web inbox.

Snapshot-then-stream without gaps: GET /api/runs/{id} returns `last_event_id`; subscribe to
/api/stream/run:{id} with `Last-Event-ID: <that value>` and anything published in between is replayed.
Phones are never exposed here (the public board masks personal data)."""
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.channels.models import Message
from app.core import sse
from app.core.db import db
from app.journeys.models import JourneyRun, TimelineEvent

router = APIRouter(prefix="/api")
CHANNEL = re.compile(r"^(global|run:\d+|call:[A-Za-z0-9_-]+)$")


def _message(m: Message) -> dict:
    return {"id": m.id, "run_id": m.run_id, "channel": m.channel, "body": m.body,
            "status": m.status, "created_at": m.created_at}


def _run(r: JourneyRun) -> dict:
    return {"id": r.id, "customer_id": r.customer_id, "family_id": r.family_id, "status": r.status,
            "cursor": r.cursor, "close_reason": r.close_reason,
            "started_at": r.started_at, "ended_at": r.ended_at}


@router.get("/runs")
async def list_runs(limit: int = 50) -> list[dict]:
    async with db.session() as s:
        rows = await s.scalars(select(JourneyRun).order_by(JourneyRun.id.desc()).limit(min(limit, 200)))
        return [_run(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: int) -> dict:
    async with db.session() as s:
        run = await s.get(JourneyRun, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        timeline = (await s.scalars(select(TimelineEvent).where(
            TimelineEvent.run_id == run_id).order_by(TimelineEvent.id))).all()
        messages = (await s.scalars(select(Message).where(
            Message.run_id == run_id).order_by(Message.id))).all()
    return {**_run(run),
            "timeline": [{"id": e.id, "kind": e.kind, "payload": e.payload_json, "ts": e.ts}
                         for e in timeline],
            "messages": [_message(m) for m in messages],
            "last_event_id": sse.hub.latest_id(f"run:{run_id}")}


@router.get("/customers/{customer_id}/messages")
async def customer_messages(customer_id: str) -> list[dict]:
    async with db.session() as s:
        rows = await s.scalars(select(Message).where(
            Message.customer_id == customer_id).order_by(Message.id))
        return [_message(m) for m in rows]


async def events(channel: str, last_id: int | None) -> AsyncIterator[dict]:
    async for item in sse.hub.subscribe(channel, last_id):
        yield {**item, "id": str(item["id"])}  # sse-starlette only encodes string ids


@router.get("/stream/{channel}")
async def stream(channel: str, last_event_id: str | None = Header(default=None)):
    if not CHANNEL.match(channel):
        raise HTTPException(404, "unknown channel")
    last = int(last_event_id) if last_event_id and last_event_id.isdigit() else None
    return EventSourceResponse(events(channel, last), ping=15)
