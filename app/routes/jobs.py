import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import require_user
from app.downloader import validate_instagram_url
from app.schemas import DownloadRequest


router = APIRouter(prefix="/api/v1/jobs")


def not_found() -> HTTPException:
    return HTTPException(404, detail={"error": "job_not_found", "message": "Job not found or expired."})


@router.post("", status_code=202)
async def create_job(body: DownloadRequest, request: Request, user: dict = Depends(require_user)):
    try:
        url = validate_instagram_url(body.url)
    except ValueError as exc:
        raise HTTPException(400, detail={"error": "invalid_url", "message": str(exc)}) from None
    job = await request.app.state.jobs.create(user, url)
    return {"id": job.id, "status": job.status}


@router.get("/{job_id}")
async def job_status(job_id: str, request: Request, user: dict = Depends(require_user)):
    job = await request.app.state.jobs.get(job_id, user["id"])
    if not job:
        raise not_found()
    result = {"id": job.id, "status": job.status}
    if job.status == "ready":
        result["size"] = job.size
    elif job.status == "failed":
        result.update(error=job.error, message=job.message)
    return result


@router.get("/{job_id}/download")
async def job_download(job_id: str, request: Request, user: dict = Depends(require_user)):
    job = await request.app.state.jobs.claim(job_id, user["id"])
    if not job:
        raise not_found()
    if job.status != "delivering" or not job.path:
        raise HTTPException(409, detail={
            "error": "job_not_ready", "message": "The job is not ready for download.", "status": job.status,
        })

    async def body_stream():
        sent = 0
        completed = False
        try:
            with job.path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    sent += len(chunk)
                    yield chunk
            completed = True
        finally:
            cleanup = asyncio.create_task(request.app.state.jobs.finish(job, completed, sent))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    return StreamingResponse(body_stream(), media_type="video/mp4", headers={
        "Content-Disposition": 'attachment; filename="reel.mp4"',
        "Content-Length": str(job.size),
        "X-Content-Type-Options": "nosniff",
    })
