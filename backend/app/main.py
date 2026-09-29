from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .transports.http import router as http_router
from .transports.mcp import mcp, mcp_app


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


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


# Mount last so the MCP ASGI app serves /mcp and OAuth metadata without
# shadowing the service's health, login, and consent routes.
app.mount("/", mcp_app)
