"""Experiment: which way of delivering the PayPal event does the model act on?

Open question from the first prompt eval: with the event injected as a mid-conversation `system`
message, neither prompt version reacted to it. This compares system / user-role / synthetic
tool-result delivery on the happy path. Costs about 15k tokens per mode per run.

    python -m evals.event_delivery
"""
import asyncio, json, re, sys

from decimal import Decimal
from evals import prompt_eval as pe
from app.voice import prompt as p, tools as t
from app.core.config import settings

FACT = "[PAYPAL EVENT] Payment captured: $49.00"
TODO = ("The order is now paid in full. Tell the customer their payment of 49 dollars has come through, "
        "thank them, say goodbye, and call end_call with outcome_hint \"paid\".")

def as_system(): return [{"role": "system", "content": p.payment_event_text("49.00")}]
def as_user():   return [{"role": "user", "content": f"{FACT}\n(Verified message from the payment system, not spoken by the customer.) {TODO}"}]
def as_tool():
    return [{"role": "assistant", "content": "", "tool_calls": [{"id": "paypal_evt_1", "type": "function",
             "function": {"name": "check_payment_status", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "paypal_evt_1", "content": json.dumps(
                {"status": "paid", "amount": "49.00", "amount_spoken": "49 dollars", "source": "paypal_event",
                 "note": "PayPal just confirmed the payment. " + TODO})}]
MODES = {"system": as_system, "user": as_user, "tool_result": as_tool}

async def one(llm, mode):
    v = pe.variant("v2")
    steps = ["Uh, yeah, okay.", "I just got busy. Sure, send me the link.", "Okay, one second."]
    # replicate play() but deliver the event our way
    from app.voice.session import CallSession
    from app.voice.tools import ToolBox
    s = CallSession(call_id="e", run_id=1, family_id="F", customer_id="c", customer_name="Asha", objective="Help the customer complete the purchase",
                    amount=Decimal("49.00"), tools=list(pe.TOOLS), offer_max_pct=10.0)
    box = ToolBox(s, pe.FakeDeps()); tools = pe.openai_tools(v["specs"](s))
    msgs = [{"role": "system", "content": v["prompt"](s)}, {"role": "user", "content": pe.OPENING}]
    async def turn():
        text, calls = "", []
        for _ in range(4):
            m = await llm.chat(msgs, tools)
            text = (text + " " + (m.get("content") or "")).strip()
            tc = m.get("tool_calls") or []
            msgs.append({"role": "assistant", "content": m.get("content") or "", **({"tool_calls": tc} if tc else {})})
            if not tc: break
            for c in tc:
                args = json.loads(c["function"]["arguments"] or "{}")
                res = await box.dispatch(c["function"]["name"], args); calls.append((c["function"]["name"], args))
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(v["view"](res))})
            if any(n == "end_call" for n, _ in calls): break
        return text, calls
    await turn()
    for u in steps:
        msgs.append({"role": "user", "content": u}); await turn()
    s.paid = True
    msgs.extend(MODES[mode]())
    text, calls = await turn()
    announced = bool(pe.PAID_CLAIM.search(text)); ended = ("end_call", {"outcome_hint": "paid"}) in calls
    return announced, ended, text[:140], calls

async def main():
    llm = pe.LLM()
    for mode in MODES:
        for i in range(2):
            a, e, text, calls = await one(llm, mode)
            print(f"{mode:12} announced={a!s:5} end_call(paid)={e!s:5} | {text!r} {calls}", flush=True)
    print("requests:", llm.requests)
asyncio.run(main())
