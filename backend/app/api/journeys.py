"""Journey builder API: show the active journey, compile a plain-English prompt, save a new version."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.accounts.models import Merchant
from app.api.access import current_merchant
from app.core.db import db
from app.journeys.compiler import compile_journey, summarize
from app.journeys.models import JourneyRecord, JourneyVersion
from app.journeys.service import InvalidJourney, save_journey

router = APIRouter(prefix="/api/journeys")


class CompileIn(BaseModel):
    prompt: str


class SaveIn(BaseModel):
    definition: dict
    journey_id: int | None = None
    source_prompt: str | None = None


@router.get("")
async def list_journeys(merchant: Merchant = Depends(current_merchant)) -> list[dict]:
    async with db.session() as s:
        out = []
        for rec in await s.scalars(select(JourneyRecord).where(
                JourneyRecord.merchant_id == merchant.id).order_by(JourneyRecord.id)):
            ver = await s.scalar(select(JourneyVersion).where(
                JourneyVersion.journey_id == rec.id, JourneyVersion.version == rec.active_version))
            if ver is None:
                continue
            out.append({"id": rec.id, "name": rec.name, "version": ver.version, "definition": ver.definition_json,
                        "summary": summarize(ver.definition_json), "source_prompt": ver.source_prompt})
        return out


@router.post("/compile")
async def compile_(body: CompileIn, request: Request,
                   _: Merchant = Depends(current_merchant)) -> dict:
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise HTTPException(503, "no LLM configured (set OPENAI_API_KEY or LLM_API_KEY)")
    result = await compile_journey(body.prompt, llm)
    return {"definition": result.definition, "errors": result.errors,
            "summary": summarize(result.definition) if result.definition else []}


@router.post("")
async def save(body: SaveIn, merchant: Merchant = Depends(current_merchant)) -> dict:
    if body.journey_id is not None:
        async with db.session() as s:
            rec = await s.get(JourneyRecord, body.journey_id)
        if rec is None or rec.merchant_id != merchant.id:
            raise HTTPException(404, "journey not found")
    try:
        journey_id, version_id = await save_journey(body.definition, journey_id=body.journey_id,
                                                    source_prompt=body.source_prompt, merchant_id=merchant.id)
    except InvalidJourney as e:
        raise HTTPException(422, {"errors": e.errors})
    return {"journey_id": journey_id, "version_id": version_id}
