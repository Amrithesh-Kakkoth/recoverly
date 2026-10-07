from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.payments.service import capture_once

router = APIRouter()

_PAGE = "<body style='font-family:sans-serif;text-align:center;padding:4rem'><h2>{}</h2></body>"


@router.get("/shop/return", response_class=HTMLResponse)
async def paypal_return(token: str, family: str | None = None) -> str:
    """PayPal appends ?token=<ORDER_ID>&PayerID=... to the return URL."""
    result = await capture_once(token)
    if result in ("captured", "family_already_paid"):
        return _PAGE.format("Paid ✓ — go back to your call.")
    return _PAGE.format("We couldn't confirm your payment yet. Please try again.")


@router.get("/shop/cancel", response_class=HTMLResponse)
async def paypal_cancel() -> str:
    return _PAGE.format("Payment cancelled. You can close this tab.")
