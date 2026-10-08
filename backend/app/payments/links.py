from app.payments.service import create_order


class PaymentLinks:
    """Implements core.interfaces.PayLinks: a fresh order in the run's family."""

    async def pay_link(self, family_id: str, amount: str, currency: str = "USD") -> str:
        return (await create_order(family_id, amount, currency))["approve_url"]
