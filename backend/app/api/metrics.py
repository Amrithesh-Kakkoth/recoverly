"""Dashboard KPIs, computed from what is persisted: runs, captures, calls and their timelines.

Not here, because nothing records it yet: AI cost per order (no token/usage tracking) and a no-journey
control cohort (every abandoned cart gets a journey)."""
from decimal import Decimal
from statistics import median

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.db import db
from app.journeys.models import JourneyRun, TimelineEvent
from app.journeys.timeutil import utc
from app.payments.models import PaymentObject
from app.voice.models import Call

router = APIRouter(prefix="/api")


@router.get("/metrics")
async def metrics() -> dict:
    async with db.session() as s:
        runs = (await s.scalars(select(JourneyRun))).all()
        recovered = [r for r in runs if r.close_reason == "recovered"]
        families = [r.family_id for r in recovered]
        revenue = Decimal(0)
        currency = None
        if families:
            caps = (await s.scalars(select(PaymentObject).where(
                PaymentObject.kind == "capture", PaymentObject.status == "COMPLETED",
                PaymentObject.family_id.in_(families)))).all()
            revenue = sum((c.amount or Decimal(0) for c in caps), Decimal(0))
            currency = next((c.currency for c in caps if c.currency), None)
        paid_at = {}
        if recovered:
            rows = await s.execute(select(TimelineEvent.run_id, func.min(TimelineEvent.ts)).where(
                TimelineEvent.kind == "event.payment_captured",
                TimelineEvent.run_id.in_([r.id for r in recovered])).group_by(TimelineEvent.run_id))
            paid_at = dict(rows.all())
        calls = await s.scalar(select(func.count()).select_from(Call)) or 0

    secs = [(utc(paid_at[r.id]) - utc(r.started_at)).total_seconds() for r in recovered if r.id in paid_at]
    ended = [r for r in runs if r.status == "done"]
    return {
        "runs_total": len(runs),
        "runs_active": len(runs) - len(ended),
        "recovered": len(recovered),
        "recovery_rate": len(recovered) / len(ended) if ended else None,
        "recovered_revenue": str(revenue), "currency": currency,
        "median_seconds_to_pay": median(secs) if secs else None,
        "calls": calls,
        "calls_per_recovered": calls / len(recovered) if recovered else None,
    }
