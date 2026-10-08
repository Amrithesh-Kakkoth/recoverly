import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router as api_router
from app.api.runs import router as runs_router
from app.api.shop import router as shop_router
from app.core.config import settings
from app.channels.web_inbox import WebInbox
from app.core.db import db
from app.detector.service import AbandonDetector
from app.journeys.engine import JourneyEngine
from app.journeys.timers import TimerLoop
from app.payments.links import PaymentLinks
from app.voice.stub import FakeCallManager
from app import all_models  # noqa: F401  (register tables)
from app.payments import service as payments
from app.payments.router import router as payments_router
from app.webhooks.router import reprocess_pending
from app.webhooks.router import router as webhooks_router

if "sandbox.paypal.com" not in settings.paypal_base_url:
    raise RuntimeError("Refusing to start: PayPal base URL must be the sandbox")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.create_all()
    payments.register()
    engine = JourneyEngine(
        channels={"whatsapp": WebInbox("whatsapp"), "web_inbox": WebInbox()},
        call_manager=FakeCallManager(),  # W3 swaps in the real Pipecat call manager
        pay_links=PaymentLinks(), family_paid=payments.family_is_paid)
    engine.register()
    timers = TimerLoop(engine)
    loop_task = asyncio.create_task(timers.run())
    detector = AbandonDetector()
    detector_task = asyncio.create_task(detector.run())
    await reprocess_pending()
    yield
    timers.stop()
    detector.stop()
    await asyncio.gather(loop_task, detector_task)


app = FastAPI(title="Recoverly", lifespan=lifespan)
app.include_router(api_router)
app.include_router(shop_router)
app.include_router(runs_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
