"""W1-B live check against the PayPal sandbox (needs creds in .env).

  python -m scripts.w1b_smoke

Creates an order, prints the approve link, waits for you to approve it as a sandbox buyer,
then runs capture_once twice to show the second call is a no-op."""
import asyncio
import uuid

from app.core.db import db
from app.main import app  # noqa: F401  (registers tables)
from app.payments.service import capture_once, create_order


async def main() -> None:
    await db.create_all()
    o = await create_order(f"smoke-{uuid.uuid4().hex[:6]}", "5.00")
    print("Approve as a sandbox buyer:", o["approve_url"])
    input("Press Enter after approving... ")
    print("first :", await capture_once(o["order_id"]))
    print("second:", await capture_once(o["order_id"]))


asyncio.run(main())
