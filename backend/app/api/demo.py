"""Config for the browser demo page: ICE servers for the call and the sandbox buyer login."""
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/api")


@router.get("/ice")
async def ice() -> dict:
    servers: list[dict] = [{"urls": "stun:stun.l.google.com:19302"}]
    urls = [u.strip() for u in settings.turn_ice_urls.split(",") if u.strip()]
    if urls:  # TURN is what makes the call work from a phone on 4G / behind NAT
        servers.append({"urls": urls, "username": settings.turn_username,
                        "credential": settings.turn_credential})
    return {"iceServers": servers}


@router.get("/demo-config")
async def demo_config() -> dict:
    cfg: dict = {"abandon_after_seconds": settings.abandon_after_seconds,
                 "voice_enabled": settings.voice_enabled,
                 "phone_calls": settings.phone_enabled}
    if settings.demo_buyer_email:  # sandbox buyer shown on the page so judges can pay
        cfg["buyer"] = {"email": settings.demo_buyer_email, "password": settings.demo_buyer_password}
    return cfg
