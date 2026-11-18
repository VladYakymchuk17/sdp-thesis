"""
Simple JWT auth for the dashboard.
Admin can see all repos and submit new ones.
"""

import hashlib
import hmac
import json
import logging
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_token(payload: dict) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    sig = hmac.new(settings.jwt_secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"


def _decode_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("bad token")
        header, body, sig = parts
        expected = hmac.new(
            settings.jwt_secret.encode(), f"{header}.{body}".encode(), hashlib.sha256
        ).digest()
        actual = urlsafe_b64decode(sig + "==")
        if not hmac.compare_digest(expected, actual):
            raise ValueError("bad sig")
        payload = json.loads(urlsafe_b64decode(body + "=="))
        if payload.get("exp", 0) < time.time():
            raise ValueError("expired")
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    return _decode_token(auth[7:])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str
    expires_in: int


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    if req.username == settings.admin_username and req.password == settings.admin_password:
        exp = int(time.time()) + 86400 * 7
        token = _make_token({"sub": req.username, "role": "admin", "exp": exp})
        return LoginResponse(token=token, username=req.username, role="admin", expires_in=86400 * 7)
    raise HTTPException(status_code=401, detail="Wrong username or password")


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"username": user["sub"], "role": user.get("role", "user")}
