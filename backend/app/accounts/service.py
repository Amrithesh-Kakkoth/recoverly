"""Accounts: password hashing (stdlib scrypt), server-side sessions, and the public demo merchant."""
import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.accounts.models import AuthSession, Merchant
from app.core.config import settings
from app.core.db import db
from app.journeys.default import DEFAULT_JOURNEY
from app.journeys.service import save_journey
from app.journeys.timeutil import utc

SESSION_DAYS = 14
_N, _R, _P = 2 ** 14, 8, 1
_UNUSABLE = "!"  # never matches a password: an account that can't sign in
MAX_FAILURES, FAILURE_WINDOW_SECONDS = 10, 900
_failures: dict[str, list[float]] = defaultdict(list)


class EmailTaken(ValueError):
    pass


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(_scrypt(password, salt)).decode()


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_password(password: str, stored: str) -> bool:
    if not stored.startswith("scrypt$"):
        return False
    _, salt, digest = stored.split("$")
    return hmac.compare_digest(_scrypt(password, base64.b64decode(salt)), base64.b64decode(digest))


def locked_out(email: str) -> bool:
    """In-memory, so it resets on restart; enough to slow password guessing on one server."""
    cutoff = time.monotonic() - FAILURE_WINDOW_SECONDS
    _failures[email] = [t for t in _failures[email] if t > cutoff]
    return len(_failures[email]) >= MAX_FAILURES


async def create_merchant(email: str, password: str, store_name: str) -> Merchant:
    async with db.session() as s:
        if await s.scalar(select(Merchant.id).where(Merchant.email == email)):
            raise EmailTaken(email)
        merchant = Merchant(email=email, password_hash=hash_password(password), store_name=store_name)
        s.add(merchant)
        await s.commit()
    await save_journey(DEFAULT_JOURNEY, merchant_id=merchant.id)  # a new store starts with a working journey
    return merchant


async def authenticate(email: str, password: str) -> Merchant | None:
    async with db.session() as s:
        merchant = await s.scalar(select(Merchant).where(Merchant.email == email))
    # Same work whether or not the account exists, so response time doesn't reveal which emails are registered.
    ok = verify_password(password, merchant.password_hash if merchant else _DUMMY_HASH)
    if merchant and ok:
        _failures.pop(email, None)
        return merchant
    _failures[email].append(time.monotonic())
    return None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def start_session(merchant_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    async with db.session() as s:
        await s.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
        s.add(AuthSession(token_hash=_hash_token(token), merchant_id=merchant_id,
                          expires_at=now + timedelta(days=SESSION_DAYS)))
        await s.commit()
    return token


async def merchant_for_token(token: str) -> Merchant | None:
    async with db.session() as s:
        session = await s.get(AuthSession, _hash_token(token))
        if session is None or utc(session.expires_at) <= datetime.now(timezone.utc):
            return None
        return await s.get(Merchant, session.merchant_id)


async def end_session(token: str) -> None:
    async with db.session() as s:
        await s.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
        await s.commit()


async def demo_merchant_id() -> int | None:
    """Owner of the public Try it storefront's runs."""
    async with db.session() as s:
        return await s.scalar(select(Merchant.id).where(Merchant.email == settings.demo_merchant_email))


async def ensure_demo_merchant() -> None:
    """Boot: the demo account exists with a journey, and signs in with DEMO_MERCHANT_PASSWORD (or not at all)."""
    password = settings.demo_merchant_password
    async with db.session() as s:
        merchant = await s.scalar(select(Merchant).where(Merchant.email == settings.demo_merchant_email))
        if merchant is None:
            merchant = Merchant(email=settings.demo_merchant_email, store_name=settings.merchant_name,
                                password_hash=hash_password(password) if password else _UNUSABLE)
            s.add(merchant)
            await s.commit()
            await save_journey(DEFAULT_JOURNEY, merchant_id=merchant.id)
        elif password and not verify_password(password, merchant.password_hash):
            merchant.password_hash = hash_password(password)
            await s.commit()
        elif not password and merchant.password_hash != _UNUSABLE:
            merchant.password_hash = _UNUSABLE
            await s.commit()
