from sqlalchemy import select

from app.core.db import db
from app.journeys.dsl import Journey
from app.journeys.lint import lint
from app.journeys.models import JourneyRecord, JourneyVersion


class InvalidJourney(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


async def save_journey(definition: dict, *, journey_id: int | None = None,
                       source_prompt: str | None = None, limits: dict | None = None) -> tuple[int, int]:
    """Lint, then save as a new version and make it active. Running journeys keep their
    own version. Returns (journey_id, version_id)."""
    j = Journey.model_validate(definition)
    errors = lint(j, limits)
    if errors:
        raise InvalidJourney(errors)
    async with db.session() as s:
        rec = await s.get(JourneyRecord, journey_id) if journey_id else None
        if rec is None:
            rec = JourneyRecord(name=j.name, trigger_event=j.trigger["event"])
            s.add(rec)
            await s.flush()
        last = await s.scalar(select(JourneyVersion.version).where(
            JourneyVersion.journey_id == rec.id).order_by(JourneyVersion.version.desc()))
        ver = JourneyVersion(journey_id=rec.id, version=(last or 0) + 1,
                             definition_json=definition, source_prompt=source_prompt)
        s.add(ver)
        await s.flush()
        rec.active_version = ver.version
        rec.name, rec.trigger_event = j.name, j.trigger["event"]
        await s.commit()
        return rec.id, ver.id
