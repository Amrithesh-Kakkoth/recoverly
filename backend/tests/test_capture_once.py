import asyncio

from app.core.events import DomainEvent
from app.payments.service import capture_once, create_order


async def _collect(bus):
    seen: list[DomainEvent] = []

    async def h(e):
        seen.append(e)

    bus.subscribe("payment.captured", h)
    return seen


async def test_happy_path_publishes_once(gw, bus):
    seen = await _collect(bus)
    o = await create_order("F1", "49.00")
    assert o["approve_url"].endswith(o["order_id"])  # payer-action link accepted
    assert await capture_once(o["order_id"], event_bus=bus) == "captured"
    assert [e.capture_id for e in seen] == [f"CAP-{o['order_id']}"]
    assert seen[0].family_id == "F1" and str(seen[0].amount) == "49.00"
    assert gw.capture_calls == [(o["order_id"], f"capture:{o['order_id']}")]


async def test_second_order_in_paid_family_is_skipped(gw, bus):
    seen = await _collect(bus)
    a, b = await create_order("F1", "49.00"), await create_order("F1", "44.10")
    await capture_once(a["order_id"], event_bus=bus)
    assert await capture_once(b["order_id"], event_bus=bus) == "family_already_paid"
    assert len(gw.capture_calls) == 1 and len(seen) == 1


async def test_concurrent_orders_in_one_family_capture_exactly_once(gw, bus):
    seen = await _collect(bus)
    a, b = await create_order("F1", "49.00"), await create_order("F1", "49.00")
    res = await asyncio.gather(capture_once(a["order_id"], event_bus=bus),
                               capture_once(b["order_id"], event_bus=bus))
    assert sorted(res) == ["captured", "family_already_paid"]
    assert len(gw.capture_calls) == 1 and len(seen) == 1


async def test_already_captured_422_counts_as_success(gw, bus):
    seen = await _collect(bus)
    o = await create_order("F1", "49.00")
    gw.orders[o["order_id"]]["captured"] = True  # captured elsewhere (e.g. return URL won)
    assert await capture_once(o["order_id"], event_bus=bus) == "captured"
    assert len(seen) == 1


async def test_non_completed_capture_is_not_paid(gw, bus):
    seen = await _collect(bus)
    gw.capture_status = "PENDING"
    o = await create_order("F1", "49.00")
    assert await capture_once(o["order_id"], event_bus=bus) == "not_completed"
    assert seen == []


async def test_unknown_order_is_never_captured(gw, bus):
    assert await capture_once("NOPE", event_bus=bus) == "unknown_order"
    assert gw.capture_calls == []


async def test_unapproved_order_returns_not_approved_without_raising(gw, bus):
    from app.payments.paypal_rest import PayPalError

    async def capture(order_id, request_id):
        raise PayPalError(422, {"details": [{"issue": "ORDER_NOT_APPROVED"}]})

    gw.capture = capture
    o = await create_order("F1", "49.00")
    assert await capture_once(o["order_id"], event_bus=bus) == "not_approved"
