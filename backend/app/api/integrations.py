"""Integration settings the dashboard can show, and a test button for the outbound webhook."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.access import current_merchant
from app.core.config import settings
from app.integrations.webhook_out import post, sample_payload

router = APIRouter(prefix="/api/integrations", dependencies=[Depends(current_merchant)])


@router.get("")
async def status() -> dict:
    return {"outbound_webhook": bool(settings.outbound_webhook_url)}


@router.post("/webhook/test")
async def test_webhook() -> dict:
    """Send a sample 'recovered' payload so a Zap (or any receiver) can learn the field names."""
    if not settings.outbound_webhook_url:
        raise HTTPException(409, "OUTBOUND_WEBHOOK_URL is not set")
    if not await post(settings.outbound_webhook_url, sample_payload(settings), attempts=1):
        raise HTTPException(502, "the webhook did not accept the sample")
    return {"ok": True}
