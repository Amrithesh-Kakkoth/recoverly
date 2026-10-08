from app.channels.models import Message
from app.core import sse
from app.core.db import db

_TEXT = {
    "cart_reminder": "Hi! You left something in your cart. Complete your purchase here: {pay_url}",
    "thank_you": "Thanks, your payment of {amount} {currency} came through!",
}


class WebInbox:
    """Fake WhatsApp thread rendered in the dashboard (the judge path). SSE push comes later."""

    def __init__(self, channel: str = "web_inbox", hub: sse.SSEHub | None = None) -> None:
        self.channel, self.hub = channel, hub or sse.hub

    async def send(self, customer_id: str, template: str, vars: dict) -> str:
        body = _TEXT.get(template, template).format_map({**{"pay_url": "", "amount": "", "currency": ""},
                                                         **{k: v for k, v in vars.items() if v is not None}})
        async with db.session() as s:
            msg = Message(customer_id=customer_id, run_id=vars.get("run_id"),
                          channel=self.channel, body=body)
            s.add(msg)
            await s.commit()
        if msg.run_id is not None:
            self.hub.publish(f"run:{msg.run_id}", "message", {
                "id": msg.id, "run_id": msg.run_id, "channel": msg.channel, "body": body})
        return f"{self.channel}:{msg.id}"
