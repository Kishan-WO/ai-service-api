"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_service.api.v1.router import api_router
from ai_service.core.config import get_settings
from ai_service.core.logging import setup_logging
from ai_service.core.middlewares import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    register_error_handlers,
)
from ai_service.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # one shared client for the whole process: connection pooling, one place for timeouts
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.DEBUG)

    app = FastAPI(title=settings.PROJECT_NAME, version="0.1.0", lifespan=lifespan)

    # Middleware added last is outermost, so the request context wraps everything.
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER, "X-Process-Time"],
        )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
