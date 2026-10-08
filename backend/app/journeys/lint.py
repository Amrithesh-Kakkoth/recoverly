"""Journey lint, in code. Returns a list of human-readable errors (empty = valid)."""
from app.journeys.dsl import Journey, edges
from app.journeys.timeutil import parse_duration

ALLOWED_TOOLS = {"send_payment_link", "check_payment_status", "apply_offer", "end_call",
                 "pause_subscription", "resume_subscription", "transfer_to_human"}
DEFAULT_LIMITS = {"max_discount_pct": 10}


def lint(j: Journey, limits: dict | None = None) -> list[str]:
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    errs: list[str] = []
    steps = j.steps

    if j.start not in steps:
        return [f"start step '{j.start}' does not exist"]

    for sid, st in steps.items():
        targets = edges(st)
        for t in targets:
            if t not in steps:
                errs.append(f"{sid}: goto '{t}' does not exist")
        if st.type == "message" and not (st.channel and st.template and st.next):
            errs.append(f"{sid}: message needs channel, template and next")
        if st.type == "wait":
            if not st.next:
                errs.append(f"{sid}: wait needs next")
            try:
                parse_duration(st.duration or "")
            except ValueError as e:
                errs.append(f"{sid}: {e}")
        if st.type == "call":
            if not st.objective:
                errs.append(f"{sid}: call needs an objective")
            if not (st.default or st.next):
                errs.append(f"{sid}: call needs a default (or next) for unmatched outcomes")
            if st.max_attempts < 1:
                errs.append(f"{sid}: max_attempts must be >= 1")
            if st.max_attempts > 1 and not st.retry_after:
                errs.append(f"{sid}: retry_after is required when max_attempts > 1")
            bad = set(st.tools) - ALLOWED_TOOLS
            if bad:
                errs.append(f"{sid}: tools not allowed: {sorted(bad)}")
            if st.offer and st.offer.get("max", 0) > limits["max_discount_pct"]:
                errs.append(f"{sid}: offer max {st.offer['max']}% exceeds merchant limit "
                            f"{limits['max_discount_pct']}%")
        if st.type == "end" and not st.result:
            errs.append(f"{sid}: end needs a result")

    for h in j.on_events:
        if h.goto not in steps:
            errs.append(f"on_events {h.event}: goto '{h.goto}' does not exist")

    # reachability: from start, plus on_events targets (reachable from anywhere)
    roots = {j.start} | {h.goto for h in j.on_events if h.goto in steps}
    seen, stack = set(), list(roots)
    while stack:
        n = stack.pop()
        if n in seen or n not in steps:
            continue
        seen.add(n)
        stack.extend(edges(steps[n]))
    for sid in steps.keys() - seen:
        errs.append(f"{sid}: unreachable")

    # every step must be able to reach an End
    ends = {sid for sid, st in steps.items() if st.type == "end"}
    can_end = set(ends)
    changed = True
    while changed:
        changed = False
        for sid, st in steps.items():
            if sid not in can_end and edges(st) & can_end:
                can_end.add(sid)
                changed = True
    for sid in seen - can_end:
        errs.append(f"{sid}: cannot reach an End")

    # loops must be bounded: every cycle has to pass through a call step (max_attempts caps it)
    non_call = {sid for sid, st in steps.items() if st.type != "call"}
    state: dict[str, int] = {}

    def has_cycle(n: str) -> bool:
        state[n] = 1
        for t in edges(steps[n]) & non_call:
            if state.get(t) == 1 or (t not in state and has_cycle(t)):
                return True
        state[n] = 2
        return False

    if any(n not in state and has_cycle(n) for n in non_call):
        errs.append("unbounded loop: every cycle must pass through a call step")

    # a journey that can see payment.captured must handle it
    sees_payment = any(st.type == "call" or "payment.captured" in st.until_any
                       for st in steps.values())
    if sees_payment and not j.handler_for("payment.captured"):
        errs.append("journey can see payment.captured but has no on_events handler for it")
    return errs
