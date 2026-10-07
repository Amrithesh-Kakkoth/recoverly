from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request) -> dict:
    # TODO W1-B: store raw (unique paypal_event_id) -> verify -> normalize -> 200 fast -> route async
    await request.body()
    return {"ok": True}
