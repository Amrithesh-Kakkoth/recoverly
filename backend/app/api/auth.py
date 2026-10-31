"""Merchant sign-up, sign-in and sign-out. The session lives in an HttpOnly cookie; SameSite=Lax stops
other sites from sending it on POSTs."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.accounts.models import Merchant
from app.accounts.service import (SESSION_DAYS, EmailTaken, authenticate, create_merchant, end_session,
                                  locked_out, start_session)
from app.api.access import COOKIE, current_merchant, session_cookie_args

router = APIRouter(prefix="/api/auth")


def _email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
        raise ValueError("enter a valid email address")
    return v


class SignupIn(BaseModel):
    email: str
    password: str = Field(min_length=10, max_length=200)
    store_name: str = Field(min_length=1, max_length=120)

    _normalize = field_validator("email")(_email)


class LoginIn(BaseModel):
    email: str
    password: str = Field(max_length=200)

    _normalize = field_validator("email")(_email)


def _public(m: Merchant) -> dict:
    return {"id": m.id, "email": m.email, "store_name": m.store_name}


async def _sign_in(response: Response, merchant: Merchant) -> dict:
    token = await start_session(merchant.id)
    response.set_cookie(value=token, max_age=SESSION_DAYS * 86400, **session_cookie_args())
    return _public(merchant)


@router.post("/signup", status_code=201)
async def signup(body: SignupIn, response: Response) -> dict:
    try:
        merchant = await create_merchant(body.email, body.password, body.store_name.strip())
    except EmailTaken:
        raise HTTPException(409, "that email already has an account")
    return await _sign_in(response, merchant)


@router.post("/login")
async def login(body: LoginIn, response: Response) -> dict:
    if locked_out(body.email):
        raise HTTPException(429, "too many attempts, try again in a few minutes")
    merchant = await authenticate(body.email, body.password)
    if merchant is None:
        raise HTTPException(401, "wrong email or password")
    return await _sign_in(response, merchant)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        await end_session(token)
    response.delete_cookie(**session_cookie_args())
    return {"ok": True}


@router.get("/me")
async def me(merchant: Merchant = Depends(current_merchant)) -> dict:
    return _public(merchant)
