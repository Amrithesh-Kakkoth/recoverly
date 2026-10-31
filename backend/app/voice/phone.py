"""Real phone calls through Twilio: outbound dial, TwiML that opens a Media Streams websocket, and
the status callback. Plain httpx against Twilio's REST API, so no Twilio SDK is needed.

Flow: manager.start_call -> TwilioDialer.dial -> Twilio rings the customer -> on answer Twilio fetches
POST /twilio/voice/{call_id} -> TwiML <Connect><Stream> -> websocket /twilio/ws -> manager.answer_phone
runs the same voice agent. A per-call token guards both routes; webhooks also verify Twilio's signature."""
import base64
import hashlib
import hmac
import logging
from urllib.parse import parse_qsl, quote
from xml.sax.saxutils import quoteattr

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket

from app.core.config import Settings, settings as default_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/twilio")
DEAD_STATUSES = {"no-answer", "busy", "failed", "canceled"}


def ws_url(cfg: Settings) -> str:
    base = cfg.public_base_url.rstrip("/")
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/twilio/ws"


def twiml(cfg: Settings, call_id: str, token: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
            f"<Stream url={quoteattr(ws_url(cfg))}>"
            f'<Parameter name="call_id" value={quoteattr(call_id)}/>'
            f'<Parameter name="token" value={quoteattr(token)}/>'
            "</Stream></Connect></Response>")


def signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's X-Twilio-Signature: HMAC-SHA1 over the URL plus the sorted POST params."""
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


class TwilioDialer:
    def __init__(self, cfg: Settings = default_settings, client: httpx.AsyncClient | None = None) -> None:
        self.cfg, self.client = cfg, client

    async def dial(self, to: str, call_id: str, token: str) -> str:
        """Place the call; returns Twilio's call SID."""
        base, q = self.cfg.public_base_url.rstrip("/"), f"?token={quote(token)}"
        form = {"To": to, "From": self.cfg.twilio_voice_from,
                "Url": f"{base}/twilio/voice/{call_id}{q}",
                "StatusCallback": f"{base}/twilio/status/{call_id}{q}", "StatusCallbackEvent": "completed",
                "Timeout": str(self.cfg.ring_timeout_seconds)}
        async with (self.client or httpx.AsyncClient(timeout=15)) as c:
            r = await c.post(f"https://api.twilio.com/2010-04-01/Accounts/{self.cfg.twilio_account_sid}/Calls.json",
                             data=form, auth=(self.cfg.twilio_account_sid, self.cfg.twilio_auth_token))
        if r.status_code >= 300:
            raise RuntimeError(f"Twilio dial failed {r.status_code}: {r.text[:200]}")
        return r.json()["sid"]


def _manager(app):
    m = getattr(app.state, "voice", None)
    if m is None:
        raise HTTPException(503, "voice agent is not configured")
    return m


async def _verified(request: Request, call_id: str, token: str) -> dict[str, str]:
    m = _manager(request.app)
    sess = m.live.get(call_id)
    if sess is None or not sess.token or not hmac.compare_digest(sess.token, token):
        raise HTTPException(404, "no such call")
    form = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))  # no python-multipart needed
    url = m.cfg.public_base_url.rstrip("/") + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    given = request.headers.get("x-twilio-signature", "")
    if not hmac.compare_digest(signature(m.cfg.twilio_auth_token, url, form), given):
        raise HTTPException(403, "bad signature")
    return form


@router.post("/voice/{call_id}")
async def voice(call_id: str, request: Request, token: str = "") -> Response:
    await _verified(request, call_id, token)
    m = _manager(request.app)
    return Response(twiml(m.cfg, call_id, token), media_type="application/xml")


@router.post("/status/{call_id}")
async def status(call_id: str, request: Request, token: str = "") -> dict:
    form = await _verified(request, call_id, token)
    await _manager(request.app).on_phone_status(call_id, form.get("CallStatus", ""))
    return {"ok": True}


@router.websocket("/ws")
async def media(websocket: WebSocket) -> None:
    from pipecat.runner.utils import parse_telephony_websocket
    await websocket.accept()
    _, data = await parse_telephony_websocket(websocket)
    body = data.body or {}
    try:
        await _manager(websocket.app).answer_phone(
            body.get("call_id", ""), body.get("token", ""), websocket, data.stream_id, data.call_id)
    except (LookupError, ValueError, HTTPException) as e:
        log.warning("rejected twilio media stream: %s", e)
        await websocket.close(code=1008)
