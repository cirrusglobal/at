"""Application entrypoint."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import DomainError
from app.models import ErrorResponse
from app.routers import auth as auth_router
from app.routers import networks as networks_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DESCRIPTION = """
Provisions AWS VPCs with multiple subnets, stores the result, and serves it back.

All endpoints except `/health` and `/v1/auth/token` require a bearer token.
Obtain one from `/v1/auth/token`, then use the **Authorize** button above.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="VPC Provisioning API",
        description=DESCRIPTION,
        version="0.1.0",
    )

    app.include_router(auth_router.router, prefix="/v1/auth", tags=["auth"])
    app.include_router(networks_router.router, prefix="/v1/networks", tags=["networks"])

    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                code=exc.code, message=exc.message, details=exc.details
            ).model_dump(),
        )

    @app.get("/health", tags=["meta"], summary="Liveness probe (unauthenticated)")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
