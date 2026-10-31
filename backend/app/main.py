import asyncio
from contextlib import asynccontextmanager


from fastapi import FastAPI

from app.api.calls import router as calls_router
from app.api.demo import router as demo_router
from app.api.router import router as api_router
from app.accounts.service import ensure_demo_merchant
from app.api.auth import router as auth_router
from app.api.integrations import router as integrations_router
from app.api.journeys import router as journeys_router
from app.api.metrics import router as metrics_router
from app.api.runs import router as runs_router
from app.api.shop import router as shop_router
from app.core.config import settings
from app.channels.web_inbox import WebInbox
from app.core.db import db
from app.detector.service import AbandonDetector
from app.integrations.webhook_out import RecoveryNotifier
from app.journeys.compiler import openai_llm
from app.journeys.engine import JourneyEngine
from app.journeys.timers import TimerLoop
from app.payments.links import PaymentLinks
from app.voice.manager import VoiceCallManager, mark_interrupted_calls
from app.voice.phone import router as twilio_router
from app.voice.pipeline import run_bot, run_phone_bot
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
    await ensure_demo_merchant()
    channels = {"whatsapp": WebInbox("whatsapp"), "web_inbox": WebInbox()}
    app.state.llm = (openai_llm(settings.llm_key, settings.llm_model, settings.llm_base_url)
                     if settings.llm_key else None)
    live = LiveCalls()
    live.register_bus()
    app.state.live_calls = live
    if settings.voice_enabled:
        voice = VoiceCallManager(live=live, deps=PaymentDeps(channels),
                                 classify=openai_classifier(settings.llm_key, settings.llm_model, settings.llm_base_url),
                                 bot_runner=run_bot, phone_runner=run_phone_bot)
        app.state.voice, call_manager = voice, voice
    else:  # no keys: scripted fake so journeys still run end to end
        app.state.voice, call_manager = None, FakeCallManager()
    engine = JourneyEngine(channels=channels, call_manager=call_manager, pay_links=PaymentLinks(),
                           family_paid=payments.family_is_paid)
    engine.register()
    await mark_interrupted_calls()               # calls cut off by the last shutdown
    await engine.recover_orphaned_calls(lambda call_id: live.get(call_id) is not None)
    timers = TimerLoop(engine)
    loop_task = asyncio.create_task(timers.run())
    detector = AbandonDetector()
    detector_task = asyncio.create_task(detector.run())
    await reprocess_pending()
    notifier_task = (asyncio.create_task(RecoveryNotifier().run())
                     if settings.outbound_webhook_url else None)
    yield
    if notifier_task:
        notifier_task.cancel()
    timers.stop()
    detector.stop()
    await asyncio.gather(loop_task, detector_task)


app = FastAPI(title="Recoverly", lifespan=lifespan)
app.include_router(api_router)
app.include_router(auth_router)
app.include_router(shop_router)
app.include_router(runs_router)
app.include_router(metrics_router)
app.include_router(journeys_router)
app.include_router(integrations_router)
app.include_router(calls_router)
app.include_router(demo_router)
app.include_router(twilio_router)

app.include_router(payments_router)
app.include_router(webhooks_router)
