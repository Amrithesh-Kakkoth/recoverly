"""The merchant's starter journey (docs/ARCHITECTURE.md section 5), seeded on first boot."""
from sqlalchemy import func, select

from app.core.db import db
from app.journeys.models import JourneyRecord
from app.journeys.service import save_journey

DEFAULT_JOURNEY = {
    "name": "Abandoned checkout recovery",
    "trigger": {"event": "checkout.abandoned", "filter": {"amount_gte": 20}},
    "settings": {},
    "on_events": [{"event": "payment.captured", "goto": "thanks"}],
    "start": "nudge",
    "steps": {
        "nudge": {"type": "message", "channel": "whatsapp", "template": "cart_reminder",
                  "include_pay_link": True, "next": "wait1"},
        "wait1": {"type": "wait", "duration": "PT30M", "until_any": ["payment.captured"],
                  "next": "call1"},
        "call1": {"type": "call", "objective": "Help the customer complete the purchase",
                  "tools": ["send_payment_link", "check_payment_status", "apply_offer", "end_call"],
                  "offer": {"kind": "discount_pct", "max": 10}, "max_attempts": 2,
                  "retry_after": "PT2H",
                  "next_by_outcome": {"paid": "thanks", "promised_to_pay": "wait2",
                                      "no_answer": "call1"},
                  "default": "lost"},
        "wait2": {"type": "wait", "duration": "PT24H", "until_any": ["payment.captured"],
                  "next": "lost"},
        "thanks": {"type": "message", "channel": "whatsapp", "template": "thank_you", "next": "won"},
        "won": {"type": "end", "result": "recovered"},
        "lost": {"type": "end", "result": "lost"},
    },
}


async def ensure_default_journey(merchant_id: int | None = None) -> bool:
    """True if it had to create one. Never touches an existing journey."""
    async with db.session() as s:
        if await s.scalar(select(func.count()).select_from(JourneyRecord).where(
                JourneyRecord.merchant_id.is_not_distinct_from(merchant_id))):
            return False
    await save_journey(DEFAULT_JOURNEY, merchant_id=merchant_id)
    return True
