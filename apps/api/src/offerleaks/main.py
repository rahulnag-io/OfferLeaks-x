"""FastAPI application entrypoint.

Routers stay thin (see architecture.md §0.3): this module wires the app
together and registers routers, nothing else. Business logic lives in
`services/`, never here or inside a router function body.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from offerleaks.api.routers import health
from offerleaks.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)

    return app


app = create_app()
