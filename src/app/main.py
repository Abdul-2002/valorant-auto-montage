from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from src.app.routes.montage import router as montage_router


def _patch_binary_formats(schema: object) -> None:
    if isinstance(schema, dict):
        # Swagger UI tends to only render file inputs when `format: binary` is present.
        if schema.get("contentMediaType") == "application/octet-stream" and schema.get("type") == "string":
            schema.setdefault("format", "binary")
        for v in schema.values():
            _patch_binary_formats(v)
    elif isinstance(schema, list):
        for item in schema:
            _patch_binary_formats(item)


def create_app() -> FastAPI:
    # Load `.env` for local/dev runs (docker-compose also loads `.env`).
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass

    app = FastAPI(title="Bot")
    app.include_router(montage_router, prefix="/montage", tags=["montage"])

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(title=app.title, version="0.1.0", routes=app.routes)
        _patch_binary_formats(openapi_schema)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[assignment]
    return app


app = create_app()
