from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Merchant(Base):
    """A store's account. Owns its customers, journeys and runs; everything else hangs off a run."""

    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    store_name: Mapped[str] = mapped_column(String(120))
    slack_webhook_url: Mapped[str | None] = mapped_column(String(500))  # a secret: never sent back to the browser
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    """A signed-in browser. Only the token's hash is stored, so a database leak can't sign anyone in."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
