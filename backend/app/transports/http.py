from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..config import get_settings


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
router = APIRouter()


@router.get("/", include_in_schema=False)
async def service_info() -> dict:
    return {
        "name": "Meal Prep Backend",
        "status": "ok",
        "mcp_endpoint": "/mcp",
    }


@router.get("/login", include_in_schema=False)
async def login() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@router.get("/oauth/consent", include_in_schema=False)
async def oauth_consent() -> FileResponse:
    return FileResponse(STATIC_DIR / "oauth-consent.html")


@router.get("/api/auth/config")
async def auth_config() -> dict:
    settings = get_settings()
    return {
        "supabaseUrl": settings.supabase_url,
        "supabaseAnonKey": settings.supabase_anon_key,
        "authRequired": settings.auth_required,
        "redirectUrl": f"{settings.app_base_url.rstrip('/')}/login",
    }


@router.get("/api/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "persistence": "supabase" if settings.supabase_configured else "demo",
        "auth_required": settings.auth_required,
        "mcp_endpoint": "/mcp",
    }
