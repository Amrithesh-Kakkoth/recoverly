"""Plain English -> journey. The LLM only produces JSON; the DSL model and lint decide whether it is valid
(up to MAX_REPAIRS repair rounds), and the human-readable summary is generated from the JSON, never by the LLM."""
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
from pydantic import ValidationError

from app.journeys.default import DEFAULT_JOURNEY
from app.journeys.dsl import Journey, edges
from app.journeys.lint import ALLOWED_TOOLS, lint
from app.journeys.timeutil import parse_duration

LLM = Callable[[list[dict]], Awaitable[str]]  # chat messages -> the model's JSON text
MAX_REPAIRS = 2

SYSTEM = f"""You turn a merchant's description of a payment-recovery journey into JSON.
Reply with exactly one JSON object and nothing else.

Step types: message, wait, call, end. There is no branching step; route only with next_by_outcome on call steps.
- message: channel ("whatsapp"), template, include_pay_link, next
- wait: duration (ISO-8601, e.g. PT30M), until_any (["payment.captured"] to stop early), next
- call: objective, tools (subset of {sorted(ALLOWED_TOOLS)}), offer ({{"kind":"discount_pct","max":N}}),
  max_attempts, retry_after (required if max_attempts > 1), next_by_outcome (paid, promised_to_pay, no_answer,
  declined, needs_human), default (required)
- end: result ("recovered" or "lost")
Every path must reach an end step. Add on_events [{{"event":"payment.captured","goto":"<step>"}}] whenever there is a
call or a wait on payment.captured. Discounts must not exceed 10%.

Example:
{json.dumps(DEFAULT_JOURNEY)}"""


@dataclass
class CompileResult:
    definition: dict | None
    errors: list[str] = field(default_factory=list)


async def compile_journey(prompt: str, llm: LLM, limits: dict | None = None) -> CompileResult:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    errors: list[str] = []
    for _ in range(MAX_REPAIRS + 1):
        reply = await llm(messages)
        try:
            definition = json.loads(reply)
            errors = lint(Journey.model_validate(definition), limits)
        except json.JSONDecodeError:
            definition, errors = None, ["reply was not valid JSON"]
        except ValidationError as e:
            definition, errors = None, [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]
        if not errors:
            return CompileResult(definition)
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "Fix these problems and reply with the full corrected JSON: "
                      + "; ".join(errors)}]
    return CompileResult(None, errors)


def openai_llm(api_key: str, model: str, base_url: str = "") -> LLM:
    """Any OpenAI-compatible endpoint, in plain JSON mode (strict json_schema isn't universal)."""
    base = (base_url or "https://api.openai.com/v1").rstrip("/")

    async def call(messages: list[dict]) -> str:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
                             json={"model": model, "response_format": {"type": "json_object"}, "messages": messages})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    return call


def _human(iso: str) -> str:
    secs = int(parse_duration(iso).total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        if secs >= size and secs % size == 0:
            n = secs // size
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return iso


def summarize(definition: dict) -> list[str]:
    """One sentence per step in the order a customer would meet them, plus trigger and interrupts."""
    j = Journey.model_validate(definition)
    floor = j.trigger.get("filter", {}).get("amount_gte")
    out = [f"Starts when {j.trigger['event'].replace('.', ' ')}" + (f" and the cart is at least {floor}." if floor else ".")]
    order, queue = [], [j.start]
    while queue:
        sid = queue.pop(0)
        if sid in order or sid not in j.steps:
            continue
        order.append(sid)
        queue += sorted(edges(j.steps[sid]))
    for sid in order:
        st = j.steps[sid]
        if st.type == "message":
            channel = "WhatsApp" if st.channel == "whatsapp" else st.channel
            out.append(f"Send a {channel} message ({st.template})" + (" with a payment link." if st.include_pay_link else "."))
        elif st.type == "wait":
            stop = " or until the customer pays" if "payment.captured" in st.until_any else ""
            out.append(f"Wait up to {_human(st.duration or 'PT0S')}{stop}.")
        elif st.type == "call":
            s = f"Call the customer to: {st.objective}."
            if st.offer:
                s += f" May offer up to {st.offer.get('max')}% off."
            if st.max_attempts > 1:
                s += f" Up to {st.max_attempts} attempts, {_human(st.retry_after or 'PT0S')} apart."
            routes = [f"{o.replace('_', ' ')} → {t}" for o, t in st.next_by_outcome.items()]
            out.append(s + (f" Then: {', '.join(routes)}; otherwise {st.default}." if routes or st.default else ""))
        else:
            out.append(f"Finish as {st.result}.")
    out += [f"If payment is captured at any point, jump to {h.goto}." for h in j.on_events if h.event == "payment.captured"]
    return out
