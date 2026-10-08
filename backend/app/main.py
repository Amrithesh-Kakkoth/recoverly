import asyncio
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.calls import router as calls_router
from app.api.demo import router as demo_router
from app.api.router import router as api_router
from app.api.runs import router as runs_router
from app.api.shop import router as shop_router
from app.core.config import REPO_ROOT, settings
from app.channels.web_inbox import WebInbox
from app.core.db import db
from app.detector.service import AbandonDetector
from app.journeys.default import ensure_default_journey
from app.journeys.engine import JourneyEngine
from app.journeys.timers import TimerLoop
from app.payments.links import PaymentLinks
from app.voice.manager import VoiceCallManager
from app.voice.pipeline import run_bot
from app.voice.registry import LiveCalls
from app.voice.stub import FakeCallManager
from app.voice.tagger import openai_classifier
from app.voice.tools import PaymentDeps
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
    await ensure_default_journey()
    channels = {"whatsapp": WebInbox("whatsapp"), "web_inbox": WebInbox()}
    live = LiveCalls()
    live.register_bus()
    app.state.live_calls = live
    if settings.voice_enabled:
        voice = VoiceCallManager(live=live, deps=PaymentDeps(channels),
                                 classify=openai_classifier(settings.llm_key, settings.llm_model, settings.llm_base_url),
                                 bot_runner=run_bot)
        app.state.voice, call_manager = voice, voice
    else:  # no keys: scripted fake so journeys still run end to end
        app.state.voice, call_manager = None, FakeCallManager()
    engine = JourneyEngine(channels=channels, call_manager=call_manager, pay_links=PaymentLinks(),
                           family_paid=payments.family_is_paid)
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
app.include_router(calls_router)
app.include_router(demo_router)

_demo = Path(REPO_ROOT) / "web" / "demo"
if _demo.is_dir():
    app.mount("/demo", StaticFiles(directory=_demo, html=True), name="demo")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/demo/")
app.include_router(payments_router)
app.include_router(webhooks_router)
