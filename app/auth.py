import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return "rr_" + secrets.token_urlsafe(32)


def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, detail={"error": "unauthorized", "message": "A Bearer token is required."})
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, detail={"error": "unauthorized", "message": "A Bearer token is required."})
    return token


async def require_user(request: Request, authorization: Annotated[str | None, Header()] = None) -> dict:
    user = await request.app.state.db.authenticate(hash_token(bearer_token(authorization)))
    if not user:
        raise HTTPException(401, detail={"error": "unauthorized", "message": "Invalid or revoked token."})
    return user


async def require_admin(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    supplied = bearer_token(authorization)
    if not hmac.compare_digest(supplied, request.app.state.settings.admin_token):
        raise HTTPException(401, detail={"error": "unauthorized", "message": "Invalid admin token."})
