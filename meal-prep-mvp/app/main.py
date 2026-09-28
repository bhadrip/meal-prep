from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .mcp_server import mcp, mcp_app


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Meal Prep MCP Server",
    description="MCP tools and apps for household food planning.",
    version="0.4.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def service_info() -> dict:
    return {
        "name": "Meal Prep MCP Server",
        "status": "ok",
        "mcp_endpoint": "/mcp",
    }


@app.get("/login", include_in_schema=False)
async def login() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/oauth/consent", include_in_schema=False)
async def oauth_consent() -> FileResponse:
    return FileResponse(STATIC_DIR / "oauth-consent.html")


@app.get("/api/auth/config")
async def auth_config() -> dict:
    settings = get_settings()
    return {
        "supabaseUrl": settings.supabase_url,
        "supabaseAnonKey": settings.supabase_anon_key,
        "authRequired": settings.auth_required,
        "redirectUrl": f"{settings.app_base_url.rstrip('/')}/login",
    }


@app.get("/api/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "persistence": "supabase" if settings.supabase_configured else "demo",
        "auth_required": settings.auth_required,
        "mcp_endpoint": "/mcp",
    }


# Mount last so the MCP ASGI app serves /mcp and OAuth metadata without
# shadowing the service's health, login, and consent routes.
app.mount("/", mcp_app)
