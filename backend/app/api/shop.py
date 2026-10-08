"""Demo storefront backend. Prices come from the server-side catalog, never from the client."""
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.api.models import Customer
from app.core.config import settings
from app.core.db import db
from app.detector import service as detector
from app.payments.service import create_order

router = APIRouter()
CATALOG = {"pro-plan": "49.00", "starter-plan": "29.00"}


class CheckoutIn(BaseModel):
    name: str
    phone: str
    sku: str = "pro-plan"
    whatsapp_optin: bool = False
    call_consent: bool = False

    @field_validator("phone")
    @classmethod
    def e164(cls, v: str) -> str:
        if not re.fullmatch(r"\+[1-9]\d{7,14}", v):
            raise ValueError("phone must be E.164, e.g. +919876543210")
        return v


@router.post("/shop/checkout")
async def checkout(body: CheckoutIn) -> dict:
    if body.sku not in CATALOG:
        raise HTTPException(404, "unknown sku")
    amount, customer_id, family_id = CATALOG[body.sku], uuid.uuid4().hex[:12], uuid.uuid4().hex[:12]
    async with db.session() as s:
        s.add(Customer(id=customer_id, name=body.name, phone_e164=body.phone,
                       whatsapp_optin=body.whatsapp_optin,
                       call_consent_at=datetime.now(timezone.utc) if body.call_consent else None))
        await s.commit()
    order = await create_order(family_id, amount)
    await detector.schedule(order_id=order["order_id"], family_id=family_id,
                            customer_id=customer_id, amount=amount)
    return {"customer_id": customer_id, "family_id": family_id, "order_id": order["order_id"],
            "amount": amount, "approve_url": order["approve_url"],
            "abandon_after_seconds": settings.abandon_after_seconds}
