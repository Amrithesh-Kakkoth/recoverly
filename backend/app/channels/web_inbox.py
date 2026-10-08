from app.channels.models import Message
from app.core.db import db

_TEXT = {
    "cart_reminder": "Hi! You left something in your cart. Complete your purchase here: {pay_url}",
    "thank_you": "Thanks, your payment of {amount} {currency} came through!",
}


class WebInbox:
    """Fake WhatsApp thread rendered in the dashboard (the judge path). SSE push comes later."""

    def __init__(self, channel: str = "web_inbox") -> None:
        self.channel = channel

    async def send(self, customer_id: str, template: str, vars: dict) -> str:
        body = _TEXT.get(template, template).format_map({**{"pay_url": "", "amount": "", "currency": ""},
                                                         **{k: v for k, v in vars.items() if v is not None}})
        async with db.session() as s:
            msg = Message(customer_id=customer_id, channel=self.channel, body=body)
            s.add(msg)
            await s.commit()
            return f"{self.channel}:{msg.id}"
