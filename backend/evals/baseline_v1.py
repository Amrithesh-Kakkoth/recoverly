"""Frozen copy of the prompt, tool descriptions and event text as they were for the first real
calls (commit dbfe30c). Only used by evals/prompt_eval.py to measure changes against."""
from evals._prompt_v1 import build_prompt  # noqa: F401

TOOL_SPECS = {
    "send_payment_link": {
        "description": "Send the customer a PayPal payment link on WhatsApp. Optionally apply a "
                       "discount percentage you are allowed to offer.",
        "properties": {"offer_pct": {"type": "number", "description": "Discount percent, optional."}},
        "required": []},
    "check_payment_status": {
        "description": "Check whether the customer has paid yet. Returns unpaid, approved or paid.",
        "properties": {}, "required": []},
    "apply_offer": {
        "description": "Apply a discount percentage to the order. Only within the allowed maximum.",
        "properties": {"pct": {"type": "number", "description": "Discount percent."}},
        "required": ["pct"]},
    "end_call": {
        "description": "End the call politely once the conversation is finished.",
        "properties": {"outcome_hint": {
            "type": "string",
            "enum": ["paid", "promised_to_pay", "declined", "callback_requested", "needs_human"]}},
        "required": ["outcome_hint"]},
    "transfer_to_human": {
        "description": "Ask for a human colleague to follow up. Use when the customer asks for one.",
        "properties": {}, "required": []},
}


def tool_specs(session) -> dict:
    return {n: TOOL_SPECS[n] for n in session.tools if n in TOOL_SPECS}


def event_text(amount) -> str:
    return f"[PAYPAL EVENT] Payment captured: ${amount}"


def result_view(result: dict) -> dict:
    """v1 gave the model the raw handler result, with no guidance fields."""
    return {k: v for k, v in result.items() if k not in ("note", "amount_spoken", "new_amount_spoken")}
