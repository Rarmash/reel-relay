import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings, load_settings
from app.database import Database
from app.downloader import Downloader
from app.jobs import JobManager
from app.routes import admin, download, jobs


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg.temp_root.mkdir(parents=True, exist_ok=True)
        await app.state.db.initialize()
        await app.state.jobs.start()
        try:
            yield
        finally:
            await app.state.jobs.stop()

    app = FastAPI(title="Reel Relay", version="1.0.0", lifespan=lifespan)
    app.state.settings = cfg
    app.state.db = Database(cfg.database_path)
    app.state.downloader = Downloader(cfg)
    app.state.jobs = JobManager(app)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "message": "The request body is invalid."},
        )

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc: HTTPException):
        content = exc.detail if isinstance(exc.detail, dict) else {"error": "request_failed", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)

    @app.get("/health")
    async def health(): return {"status": "ok"}

    app.include_router(download.router)
    app.include_router(jobs.router)
    app.include_router(admin.router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = create_app()
