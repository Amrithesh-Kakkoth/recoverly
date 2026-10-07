from app.core.events import DomainEvent, EventBus


async def test_bus_dedupes_capture_events():
    bus, seen = EventBus(), []

    async def h(e):
        seen.append(e)

    bus.subscribe("payment.captured", h)
    ev = DomainEvent(type="payment.captured", capture_id="C1")
    await bus.publish(ev)
    await bus.publish(ev.model_copy(update={"source": "webhook"}))
    assert len(seen) == 1
