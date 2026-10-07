class WebInbox:
    """Fake WhatsApp thread rendered in the dashboard over SSE (the judge path)."""

    async def send(self, customer_id: str, template: str, vars: dict) -> str:
        # TODO W2: persist to messages, push on SSE run:{id}
        return "web-inbox-msg"
