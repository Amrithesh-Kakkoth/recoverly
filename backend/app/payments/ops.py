"""paypal_ops logging shared by the REST and Agent Toolkit paths. Best effort: a logging
failure must never fail a payment."""
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar

from app.core.db import db
from app.payments.models import PayPalOp

log = logging.getLogger(__name__)

# Callers (journey engine, voice tools) set this so ops are attributed to a run/call.
op_context: ContextVar[dict] = ContextVar("paypal_op_context", default={})


@asynccontextmanager
async def logged(op: str, via: str, request_id: str | None = None):
    start, status = time.perf_counter(), "ok"
    try:
        yield
    except Exception as e:
        status = f"error:{getattr(e, 'status', 'x')}"
        raise
    finally:
        try:
            ctx = op_context.get()
            async with db.session() as s:
                s.add(PayPalOp(op=op, via=via, request_id=request_id, status=status,
                               latency_ms=int((time.perf_counter() - start) * 1000),
                               run_id=ctx.get("run_id"), call_id=ctx.get("call_id")))
                await s.commit()
        except Exception:
            log.exception("failed to record paypal op %s", op)
