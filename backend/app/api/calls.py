"""WebRTC signalling for the browser 'Answer call' button + call detail for the dashboard."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.access import visible_call
from app.core.db import db
from app.voice.models import Call, Outcome

router = APIRouter(prefix="/api/calls")


class Offer(BaseModel):
    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None


class IceCandidateIn(BaseModel):
    candidate: str
    sdp_mid: str
    sdp_mline_index: int


class IcePatch(BaseModel):
    pc_id: str
    candidates: list[IceCandidateIn]


def _manager(request: Request):
    m = getattr(request.app.state, "voice", None)
    if m is None:
        raise HTTPException(503, "voice agent is not configured (set OpenAI, Deepgram, Cartesia keys)")
    return m


@router.post("/{call_id}/offer")
async def answer(call_id: str, offer: Offer, request: Request, family: str | None = None) -> dict:
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest
    manager = _manager(request)
    await visible_call(call_id, request, family)
    try:
        out = await manager.answer(call_id, SmallWebRTCRequest(**offer.model_dump()))
    except LookupError:
        raise HTTPException(404, "no such ringing call")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return out or {}


@router.patch("/{call_id}/offer")
async def ice(call_id: str, patch: IcePatch, request: Request, family: str | None = None) -> dict:
    from pipecat.transports.smallwebrtc.request_handler import IceCandidate, SmallWebRTCPatchRequest
    m = _manager(request)
    await visible_call(call_id, request, family)
    await m._request_handler().handle_patch_request(SmallWebRTCPatchRequest(
        pc_id=patch.pc_id, candidates=[IceCandidate(c.candidate, c.sdp_mid, c.sdp_mline_index)
                                       for c in patch.candidates]))
    return {"ok": True}


@router.get("/{call_id}")
async def get_call(call_id: str, request: Request, family: str | None = None) -> dict:
    await visible_call(call_id, request, family)
    live = getattr(request.app.state, "live_calls", None)
    sess = live.get(call_id) if live else None
    if sess is not None:  # in progress: serve live state
        return {"id": call_id, "status": sess.status, "transcript": sess.transcript,
                "tool_calls": sess.tool_calls, "voice_to_voice_ms": sess.latency_ms}
    async with db.session() as s:
        call = await s.get(Call, call_id)
        if call is None:
            raise HTTPException(404, "call not found")
        out = await s.scalar(select(Outcome).where(Outcome.call_id == call_id))
    return {"id": call_id, "status": call.status, "transcript": call.transcript_json or [],
            "tool_calls": call.tool_calls_json or [],
            "voice_to_voice_ms": (call.latency_json or {}).get("voice_to_voice_ms", []),
            "outcome": out.label if out else None, "summary": out.summary if out else None,
            "overridden_by": out.overridden_by if out else None}
