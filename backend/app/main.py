from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import auth, roles, users
from app.core.config import Settings, get_settings
from app.db.mongo import create_client, ensure_indexes, get_database
from app.seed import seed_defaults
from app.services.errors import ServiceError

logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = create_client(settings)
        app.state.db = get_database(client, settings)
        await ensure_indexes(app.state.db)
        await seed_defaults(app.state.db, settings)
        try:
            yield
        finally:
            await client.close()

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        # Interactive API docs are handy in development, noise in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Services raise domain errors (NotFound, Conflict, ...); render them as FastAPI-style JSON.
    @app.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/api/health", tags=["health"])
    async def health(request: Request) -> dict[str, str]:
        try:
            await request.app.state.db.command("ping")
        except Exception:
            raise HTTPException(503, detail="Database unavailable") from None
        return {"status": "ok"}

    # Register new modules here.
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(roles.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.api_host, port=s.api_port, reload=not s.is_production)
