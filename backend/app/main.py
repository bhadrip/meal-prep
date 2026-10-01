from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .application.errors import ApplicationError, RepositoryError, RevisionConflictError
from .invitations import router as invitations_router
from .transports.http import router as http_router
from .transports.mcp import mcp, mcp_app


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Meal Prep Backend",
    description="Application services exposed through MCP and HTTP transport adapters.",
    version="0.6.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(http_router)
app.include_router(invitations_router)


@app.exception_handler(ApplicationError)
async def application_error_handler(_, exc: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RevisionConflictError)
async def revision_conflict_handler(_, exc: RevisionConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(RepositoryError)
async def repository_error_handler(_, exc: RepositoryError) -> JSONResponse:
    logger.error("Repository operation failed: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "This part of Meal Prep is temporarily unavailable. Please try again later."},
    )


# Mount last so the MCP ASGI app serves /mcp and OAuth metadata without
# shadowing the service's health, login, and consent routes.
app.mount("/", mcp_app)
