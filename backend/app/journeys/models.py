from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class JourneyRecord(Base):
    __tablename__ = "journeys"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    trigger_event: Mapped[str] = mapped_column(String(48))
    active_version: Mapped[int | None] = mapped_column()


class JourneyVersion(Base):
    __tablename__ = "journey_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    journey_id: Mapped[int] = mapped_column(ForeignKey("journeys.id"), index=True)
    version: Mapped[int] = mapped_column()
    definition_json: Mapped[dict] = mapped_column(JSON)
    source_prompt: Mapped[str | None] = mapped_column(Text)


class JourneyRun(Base):
    """One active run per family (partial unique index). status: running | waiting | in_call | done."""

    __tablename__ = "journey_runs"
    __table_args__ = (Index("uq_one_active_run_per_family", "family_id", unique=True,
                            postgresql_where=text("status != 'done'"),
                            sqlite_where=text("status != 'done'")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True)
    journey_version_id: Mapped[int] = mapped_column(ForeignKey("journey_versions.id"))
    customer_id: Mapped[str] = mapped_column(String(64))
    family_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="running")
    cursor: Mapped[str] = mapped_column(String(48))
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    time_scale: Mapped[float] = mapped_column(Float, default=1.0)
    close_reason: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StepRun(Base):
    __tablename__ = "step_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("journey_runs.id"), index=True)
    step_id: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16), default="running")
    input_json: Mapped[dict | None] = mapped_column(JSON)
    output_json: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class Timer(Base):
    """Polled every second; survives restarts. kind: wait | retry | call_window."""

    __tablename__ = "timers"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("journey_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TimelineEvent(Base):
    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("journey_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
