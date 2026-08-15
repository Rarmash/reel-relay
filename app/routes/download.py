import logging
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import require_user
from app.downloader import DownloadError, DownloadTimeout, FileTooLarge, validate_instagram_url
from app.schemas import DownloadRequest

router = APIRouter()
log = logging.getLogger("reel_relay.download")


@router.post("/api/v1/download")
async def download(body: DownloadRequest, request: Request, user: dict = Depends(require_user)):
    started = time.monotonic()
    request_id = request.state.request_id
    try:
        url = validate_instagram_url(body.url)
    except ValueError as exc:
        raise HTTPException(400, detail={"error": "invalid_url", "message": str(exc)}) from None
    try:
        directory, path = await request.app.state.downloader.download(url)
    except DownloadTimeout:
        await request.app.state.db.record_event(user["id"], False)
        raise HTTPException(504, detail={"error": "download_timeout", "message": "The download timed out."}) from None
    except FileTooLarge:
        await request.app.state.db.record_event(user["id"], False)
        raise HTTPException(413, detail={"error": "file_too_large", "message": "The Reel exceeds the configured size limit."}) from None
    except DownloadError as exc:
        await request.app.state.db.record_event(user["id"], False)
        log.warning("request=%s user_id=%s status=failed reason=%s", request_id, user["id"], exc)
        raise HTTPException(502, detail={"error": "download_failed", "message": "Instagram did not allow this Reel to be downloaded."}) from None

    downloaded = path.stat().st_size
    async def body_stream():
        sent = 0
        completed = False
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    sent += len(chunk)
                    yield chunk
            completed = True
        finally:
            shutil.rmtree(directory, ignore_errors=True)
            await request.app.state.db.record_event(user["id"], completed, downloaded, sent)
            log.info(
                "request=%s user_id=%s user=%s status=%s size=%s duration=%.2f",
                request_id, user["id"], user["name"], "success" if completed else "interrupted",
                sent, time.monotonic() - started,
            )
    return StreamingResponse(body_stream(), media_type="video/mp4", headers={
        "Content-Disposition": 'attachment; filename="reel.mp4"',
        "Content-Length": str(downloaded),
        "X-Content-Type-Options": "nosniff",
    })
