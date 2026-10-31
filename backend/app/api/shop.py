"""Demo storefront backend. Prices come from the server-side catalog, never from the client."""
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from app.accounts.models import Merchant
from app.accounts.service import demo_merchant_id
from app.api.access import optional_merchant
from app.api.models import Customer
from app.core.config import settings
from app.core.db import db
from app.detector import service as detector
from app.journeys.models import JourneyRun
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
async def checkout(body: CheckoutIn, merchant: Merchant | None = Depends(optional_merchant)) -> dict:
    """Signed in: the run is that merchant's. Otherwise it belongs to the demo store."""
    if body.sku not in CATALOG:
        raise HTTPException(404, "unknown sku")
    amount, customer_id = CATALOG[body.sku], uuid.uuid4().hex[:12]
    family_id = uuid.uuid4().hex  # also the visitor's access to this run (access.py), so it must be unguessable
    merchant_id = merchant.id if merchant else await demo_merchant_id()
    async with db.session() as s:
        s.add(Customer(id=customer_id, merchant_id=merchant_id, name=body.name, phone_e164=body.phone,
                       whatsapp_optin=body.whatsapp_optin,
                       call_consent_at=datetime.now(timezone.utc) if body.call_consent else None))
        await s.commit()
    order = await create_order(family_id, amount)
    await detector.schedule(order_id=order["order_id"], family_id=family_id,
                            customer_id=customer_id, amount=amount)
    return {"customer_id": customer_id, "family_id": family_id, "order_id": order["order_id"],
            "amount": amount, "approve_url": order["approve_url"],
            "abandon_after_seconds": settings.abandon_after_seconds}


@router.get("/shop/runs/{family_id}")
async def run_for_checkout(family_id: str) -> dict:
    """Try it polls this until the abandoned checkout starts its run."""
    async with db.session() as s:
        run_id = await s.scalar(select(JourneyRun.id).where(JourneyRun.family_id == family_id)
                                .order_by(JourneyRun.id.desc()))
    return {"run_id": run_id}
