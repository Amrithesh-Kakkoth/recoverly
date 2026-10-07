from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router as api_router
from app.core.config import settings
from app.core.db import db
from app.payments import models as _payment_models  # noqa: F401  (register tables)
from app.payments import service as payments
from app.payments.router import router as payments_router
from app.webhooks import models as _webhook_models  # noqa: F401
from app.webhooks.router import reprocess_pending
from app.webhooks.router import router as webhooks_router

if "sandbox.paypal.com" not in settings.paypal_base_url:
    raise RuntimeError("Refusing to start: PayPal base URL must be the sandbox")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.create_all()
    payments.register()
    await reprocess_pending()
    yield


app = FastAPI(title="Recoverly", lifespan=lifespan)
app.include_router(api_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
