from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PaymentObject(Base):
    """kind = order | capture. A family is every order created for one journey run."""

    __tablename__ = "payment_objects"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    paypal_id: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
