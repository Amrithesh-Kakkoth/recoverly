import copy
from datetime import datetime, timedelta, timezone

SAMPLE = {
    "name": "Abandoned checkout recovery",
    "trigger": {"event": "checkout.abandoned", "filter": {"amount_gte": 20}},
    "settings": {},
    "on_events": [{"event": "payment.captured", "goto": "thanks"}],
    "start": "nudge",
    "steps": {
        "nudge": {"type": "message", "channel": "web_inbox", "template": "cart_reminder",
                  "include_pay_link": True, "next": "wait1"},
        "wait1": {"type": "wait", "duration": "PT30M", "until_any": ["payment.captured"],
                  "next": "call1"},
        "call1": {"type": "call", "objective": "Help the customer complete the purchase",
                  "tools": ["send_payment_link", "check_payment_status", "apply_offer", "end_call"],
                  "offer": {"kind": "discount_pct", "max": 10}, "max_attempts": 2,
                  "retry_after": "PT2H",
                  "next_by_outcome": {"paid": "thanks", "promised_to_pay": "wait2",
                                      "no_answer": "call1"},
                  "default": "lost"},
        "wait2": {"type": "wait", "duration": "PT24H", "until_any": ["payment.captured"],
                  "next": "lost"},
        "thanks": {"type": "message", "channel": "web_inbox", "template": "thank_you", "next": "won"},
        "won": {"type": "end", "result": "recovered"},
        "lost": {"type": "end", "result": "lost"},
    },
}


def sample(**mods) -> dict:
    d = copy.deepcopy(SAMPLE)
    for path, value in mods.items():  # "steps.call1.max_attempts" -> value
        node = d
        *parents, leaf = path.split(".")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return d


class FakeClock:
    def __init__(self, start=None):
        self.t = start or datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)
