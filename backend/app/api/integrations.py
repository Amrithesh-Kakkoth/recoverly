"""Integration settings: each merchant's Slack channel, and a test button for the operator's webhook."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.accounts.models import Merchant
from app.api.access import current_merchant
from app.core.config import settings
from app.core.db import db
from app.integrations.webhook_out import post, sample_payload

router = APIRouter(prefix="/api/integrations")
# Only Slack's own host: the server POSTs here, so an arbitrary URL would let anyone probe internal addresses.
SLACK_URL = re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9_/-]+")


class SlackIn(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def slack_only(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 500 or not SLACK_URL.fullmatch(v):
            raise ValueError("paste a Slack webhook URL, starting https://hooks.slack.com/services/")
        return v


@router.get("")
async def status(merchant: Merchant = Depends(current_merchant)) -> dict:
    return {"outbound_webhook": bool(settings.outbound_webhook_url), "slack": bool(merchant.slack_webhook_url)}


async def _set_slack(merchant_id: int, url: str | None) -> None:
    async with db.session() as s:
        (await s.get(Merchant, merchant_id)).slack_webhook_url = url
        await s.commit()


@router.put("/slack")
async def connect_slack(body: SlackIn, merchant: Merchant = Depends(current_merchant)) -> dict:
    await _set_slack(merchant.id, body.url)
    return {"slack": True}


@router.delete("/slack")
async def disconnect_slack(merchant: Merchant = Depends(current_merchant)) -> dict:
    await _set_slack(merchant.id, None)
    return {"slack": False}


@router.post("/slack/test")
async def test_slack(merchant: Merchant = Depends(current_merchant)) -> dict:
    if not merchant.slack_webhook_url:
        raise HTTPException(409, "connect Slack first")
    message = {"text": f"Recoverly is connected. Recovery results for {merchant.store_name} will appear here."
               .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}
    if not await post(merchant.slack_webhook_url, message, attempts=1):
        raise HTTPException(502, "Slack didn't accept the message. Check the webhook URL")
    return {"ok": True}


@router.post("/webhook/test")
async def test_webhook(_: Merchant = Depends(current_merchant)) -> dict:
    """Send a sample 'recovered' payload so a Zap (or any receiver) can learn the field names."""
    if not settings.outbound_webhook_url:
        raise HTTPException(409, "OUTBOUND_WEBHOOK_URL is not set")
    if not await post(settings.outbound_webhook_url, sample_payload(settings), attempts=1):
        raise HTTPException(502, "the webhook did not accept the sample")
    return {"ok": True}
