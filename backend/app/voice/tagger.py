"""Outcome tagger: structured {label, confidence, summary, objections} from the transcript, then
deterministic overrides, in order: family paid -> paid; no-answer/busy -> no_answer; transfer
requested -> needs_human; confidence < 0.6 -> needs_human."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

LABELS = ["paid", "promised_to_pay", "declined", "callback_requested", "no_answer", "needs_human"]
MIN_CONFIDENCE = 0.6

Classifier = Callable[[list[dict], str | None], Awaitable[dict]]


@dataclass
class Tagged:
    label: str
    confidence: float
    summary: str
    objections: list[str] = field(default_factory=list)
    overridden_by: str | None = None


async def tag_outcome(*, transcript: list[dict], hint: str | None, family_paid: bool,
                      no_answer: bool, transfer_requested: bool,
                      classify: Classifier | None) -> Tagged:
    raw = {"label": hint if hint in LABELS else "needs_human", "confidence": 0.5 if not hint else 0.8,
           "summary": "", "objections": []}
    if classify and transcript and not no_answer:
        try:
            raw = {**raw, **await classify(transcript, hint)}
        except Exception:
            pass  # fall back to the agent's hint; the overrides below still apply
    label = raw["label"] if raw["label"] in LABELS else "needs_human"
    t = Tagged(label, float(raw["confidence"]), raw.get("summary", ""), list(raw.get("objections", [])))
    if family_paid:
        t.label, t.overridden_by = "paid", "family_paid"
    elif no_answer:
        t.label, t.overridden_by = "no_answer", "no_answer"
    elif transfer_requested:
        t.label, t.overridden_by = "needs_human", "transfer"
    elif t.confidence < MIN_CONFIDENCE:
        t.label, t.overridden_by = "needs_human", "low_confidence"
    return t


def openai_classifier(api_key: str, model: str) -> Classifier:
    schema = {"type": "object", "additionalProperties": False,
              "required": ["label", "confidence", "summary", "objections"],
              "properties": {"label": {"type": "string", "enum": LABELS},
                             "confidence": {"type": "number"}, "summary": {"type": "string"},
                             "objections": {"type": "array", "items": {"type": "string"}}}}

    async def classify(transcript: list[dict], hint: str | None) -> dict:
        text = "\n".join(f"{m['role']}: {m['text']}" for m in transcript if m.get("text"))
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "response_format": {"type": "json_schema", "json_schema": {
                    "name": "outcome", "strict": True, "schema": schema}},
                      "messages": [
                          {"role": "system", "content": "Classify the outcome of this payment-recovery "
                           "phone call. 'paid' only if the transcript shows a [PAYPAL EVENT] payment "
                           "confirmation. Give confidence 0-1."},
                          {"role": "user", "content": f"Agent hint: {hint}\n\n{text}"}]})
            r.raise_for_status()
        import json
        return json.loads(r.json()["choices"][0]["message"]["content"])

    return classify
