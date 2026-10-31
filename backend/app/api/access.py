"""Who may see what. Dashboard routes need a signed-in merchant, and a merchant only sees its own runs.
A Try it visitor has no account: its checkout's family id is the capability for that one run, and is
only ever returned to whoever made the checkout. Anything else is a 404, so ids can't be probed."""
import hmac

from fastapi import HTTPException, Request

from app.accounts.models import Merchant
from app.accounts.service import merchant_for_token
from app.core.config import settings
from app.core.db import db
from app.journeys.models import JourneyRun
from app.voice.models import Call

COOKIE = "recoverly_session"


async def optional_merchant(request: Request) -> Merchant | None:
    token = request.cookies.get(COOKIE)
    return await merchant_for_token(token) if token else None


async def current_merchant(request: Request) -> Merchant:
    merchant = await optional_merchant(request)
    if merchant is None:
        raise HTTPException(401, "sign in required")
    return merchant


def session_cookie_args() -> dict:
    return {"key": COOKIE, "httponly": True, "samesite": "lax", "path": "/",
            "secure": settings.public_base_url.startswith("https://")}


async def visible_run(run_id: int, request: Request, family: str | None) -> JourneyRun:
    async with db.session() as s:
        run = await s.get(JourneyRun, run_id)
    if run is not None:
        merchant = await optional_merchant(request)
        if merchant is not None and run.merchant_id == merchant.id:
            return run
        if family and hmac.compare_digest(family, run.family_id):
            return run
    raise HTTPException(404, "run not found")


async def visible_call(call_id: str, request: Request, family: str | None) -> Call:
    async with db.session() as s:
        call = await s.get(Call, call_id)
    if call is None or call.run_id is None:
        raise HTTPException(404, "call not found")
    await visible_run(call.run_id, request, family)
    return call
