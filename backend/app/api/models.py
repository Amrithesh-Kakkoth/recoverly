from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    whatsapp_optin: Mapped[bool] = mapped_column(Boolean, default=False)
    call_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allowlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    locale: Mapped[str] = mapped_column(String(10), default="en")
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
