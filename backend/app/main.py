from fastapi import FastAPI

from app.api.router import router as api_router
from app.core.config import settings
from app.webhooks.router import router as webhooks_router

if "sandbox.paypal.com" not in settings.paypal_base_url:
    raise RuntimeError("Refusing to start: PayPal base URL must be the sandbox")

app = FastAPI(title="Recoverly")
app.include_router(api_router)
app.include_router(webhooks_router)
