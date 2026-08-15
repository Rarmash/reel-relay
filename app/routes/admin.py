from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import hash_token, new_token, require_admin
from app.schemas import TokenCreate

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])


@router.post("/tokens", status_code=201)
async def create_token(body: TokenCreate, request: Request):
    token = new_token()
    row = await request.app.state.db.create_token(body.name.strip(), hash_token(token))
    return {"id": row["id"], "name": row["name"], "token": token}


@router.get("/tokens")
async def list_tokens(request: Request):
    return {"tokens": await request.app.state.db.list_tokens()}


@router.post("/tokens/{token_id}/revoke")
async def revoke_token(token_id: int, request: Request):
    if not await request.app.state.db.revoke_token(token_id):
        raise HTTPException(404, detail={"error": "not_found", "message": "Active token not found."})
    return {"status": "revoked", "id": token_id}


@router.get("/stats")
async def stats(request: Request, month: str | None = None):
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(400, detail={"error": "invalid_month", "message": "Use YYYY-MM."}) from None
    return await request.app.state.db.stats(month)
