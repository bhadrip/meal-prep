from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..application import MealPrepServices
from ..auth import SupabaseTokenVerifier
from ..config import get_settings
from ..container import services_for_request
from ..infrastructure.repositories import SupabaseRepository
from ..sharing import read_shared_recipe, render_shared_recipe_page


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
router = APIRouter()
bearer = HTTPBearer(auto_error=False)


async def web_services(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> MealPrepServices:
    """Use the browser's Supabase session for the same RLS-scoped services as MCP."""
    settings = get_settings()
    if not settings.supabase_configured:
        return services_for_request()
    if not credentials:
        if settings.auth_required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in to continue",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return services_for_request()
    access = await SupabaseTokenVerifier(settings).verify_token(credentials.credentials)
    if not access:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return services_for_request(access.token)


WebServices = Annotated[MealPrepServices, Depends(web_services)]


@router.get("/", include_in_schema=False)
async def website_home() -> FileResponse:
    return FileResponse(STATIC_DIR / "landing.html")


@router.get("/app", include_in_schema=False)
async def website() -> FileResponse:
    return FileResponse(STATIC_DIR / "app.html")


@router.get("/login", include_in_schema=False)
async def login() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@router.get("/invite", include_in_schema=False)
async def invitation_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "invite.html")


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
        "website": "/",
        "mcp_endpoint": "/mcp",
    }


@router.get("/api/app/snapshot")
async def app_snapshot(services: WebServices) -> dict:
    return await services.household.snapshot()


@router.get("/api/app/bootstrap")
async def app_bootstrap(services: WebServices) -> dict:
    """Load the website's initial household data with one authentication check."""
    repository = services.household.repository
    if isinstance(repository, SupabaseRepository):
        pending = await repository.rpc("pending_household_invitations")
        invitations = pending.get("invitations") or []
        if not pending.get("hasHousehold") and invitations:
            return {"needsInvitationReview": True, "pendingInvites": invitations}
        snapshot, access, memberships = await asyncio.gather(
            services.household.snapshot(),
            repository.rpc("household_access"),
            repository.list_households(),
        )
        return {
            "snapshot": snapshot,
            "access": access,
            "memberships": memberships,
            "pendingInvites": invitations,
        }
    return {"snapshot": await services.household.snapshot(), "pendingInvites": []}


@router.get("/api/notifications")
async def list_notifications(services: WebServices) -> dict:
    repository = services.household.repository
    if not isinstance(repository, SupabaseRepository):
        return {"items": [], "unreadCount": 0}
    rows = await repository.request("GET", "notifications", params={
        "select": "id,household_id,kind,title,target_path,created_at,read_at",
        "order": "created_at.desc", "limit": "100",
    }) or []
    return {"items": rows, "unreadCount": sum(row["read_at"] is None for row in rows)}


@router.patch("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: UUID, services: WebServices) -> dict:
    repository = services.household.repository
    if not isinstance(repository, SupabaseRepository):
        raise HTTPException(status_code=404, detail="Notification not found")
    rows = await repository.request("PATCH", "notifications",
        params={"id": f"eq.{notification_id}"},
        json={"read_at": datetime.now(UTC).isoformat()}) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"id": rows[0]["id"], "readAt": rows[0]["read_at"]}


@router.get("/api/household")
async def get_household(services: WebServices) -> dict:
    return await services.household.get_context()


@router.patch("/api/household")
async def update_household(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.household.update_preferences(
        household_size=payload.get("householdSize"),
        dietary_restrictions=payload.get("dietaryRestrictions"),
        store_priority=payload.get("storePriority"),
        planning_preferences=payload.get("planningPreferences"),
        complete_onboarding=payload.get("completeOnboarding", False),
    )


@router.get("/api/dashboard-layout")
async def get_dashboard_layout(services: WebServices) -> dict:
    return await services.household.get_dashboard_layout()


@router.patch("/api/dashboard-layout")
async def configure_dashboard(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.household.configure_dashboard(
        card_order=payload.get("cardOrder"),
        hidden_cards=payload.get("hiddenCards"),
        reset_to_default=payload.get("resetToDefault", False),
    )


@router.get("/api/recipes")
async def search_recipes(
    services: WebServices,
    query: str = "",
    tag: str = "",
    limit: int = Query(25, ge=1, le=25),
) -> dict:
    items = await services.food.search_recipes(query=query, limit=limit, tag=tag)
    return {"items": items, "count": len(items)}


@router.get("/api/recipe-tags")
async def list_recipe_tags(services: WebServices) -> dict:
    items = await services.food.list_recipe_tags()
    return {"items": items, "count": len(items)}


@router.get("/api/recipes/{recipe_id}")
async def get_recipe(recipe_id: str, services: WebServices) -> dict:
    return await services.food.get_recipe(recipe_id)


@router.put("/api/recipes")
async def save_recipe(recipe: dict[str, Any], services: WebServices) -> dict:
    return await services.food.save_recipe(recipe)


@router.delete("/api/recipes/{recipe_id}")
async def archive_recipe(recipe_id: str, services: WebServices) -> dict:
    return await services.food.archive_recipe(recipe_id)


@router.post("/api/recipes/{recipe_id}/shares")
async def create_recipe_share(recipe_id: str, services: WebServices) -> dict:
    share = await services.food.create_recipe_share(recipe_id)
    return {**share, "url": f"{get_settings().app_base_url.rstrip('/')}/s/{share['token']}"}


@router.get("/api/recipe-shares")
async def list_recipe_shares(services: WebServices) -> dict:
    items = await services.food.list_recipe_shares()
    return {"items": items, "count": len(items)}


@router.delete("/api/recipe-shares/{share_id}")
async def revoke_recipe_share(share_id: str, services: WebServices) -> dict:
    return await services.food.revoke_recipe_share(share_id)


@router.get("/api/recipes/{recipe_id}/lessons")
async def get_recipe_lessons(recipe_id: str, services: WebServices, limit: int = 50) -> dict:
    return await services.feedback.recipe_feedback_summary(recipe_id, limit)


@router.get("/api/pantry")
async def get_pantry(services: WebServices) -> dict:
    items = await services.food.get_pantry()
    return {"items": items, "count": len(items)}


@router.put("/api/pantry")
async def update_pantry_item(item: dict[str, Any], services: WebServices) -> dict:
    return await services.food.update_pantry_item(item)


@router.post("/api/pantry/use")
async def record_pantry_use(use: dict[str, Any], services: WebServices) -> dict:
    return await services.food.record_pantry_use(
        use.get("itemId"), use.get("quantity"), use.get("recipeId"), use.get("mealTitle"),
    )


@router.get("/api/meal-plan")
async def get_meal_plan(services: WebServices, week_start: str | None = None) -> dict:
    return {"plan": await services.planning.get_meal_plan(week_start)}


@router.get("/api/meal-plan-rules")
async def get_meal_plan_rules(services: WebServices, revision_id: str | None = None) -> dict:
    return {"rules": await services.planning.get_rules(revision_id)}


@router.get("/api/meal-plan-rules/history")
async def get_meal_plan_rule_history(services: WebServices, limit: int = 20) -> dict:
    return {"items": await services.planning.get_rule_history(limit)}


@router.put("/api/meal-plan-rules")
async def save_meal_plan_rules(document: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.save_rules(document.get("text"), document.get("expectedRevision"))


@router.put("/api/meal-plan")
async def save_meal_plan(plan: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.save_meal_plan(plan)


@router.get("/api/shopping-list")
async def get_shopping_list(services: WebServices, list_id: str | None = None) -> dict:
    return {"shoppingList": await services.shopping.get(list_id)}


@router.put("/api/shopping-list")
async def save_shopping_list(
    shopping_list: dict[str, Any], services: WebServices
) -> dict:
    return await services.shopping.save(shopping_list)


@router.post("/api/shopping-list/items")
async def add_shopping_item(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.shopping.add_item(payload.get("item", {}), payload.get("listId"))


@router.patch("/api/shopping-list/items/{item_id}")
async def mark_item_purchased(
    item_id: str,
    services: WebServices,
    payload: dict[str, Any] = Body(default={}),
) -> dict:
    return await services.shopping.mark_purchased(
        item_id,
        payload.get("purchased", True),
        payload.get("purchasedQuantity"),
    )


@router.get("/api/schedule")
async def get_weekly_schedule(services: WebServices, week_start: str | None = None) -> dict:
    return {"schedule": await services.planning.get_schedule(week_start)}


@router.put("/api/schedule")
async def save_weekly_schedule(schedule: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.save_schedule(schedule)


@router.get("/api/planning-context")
async def get_planning_context(services: WebServices, week_start: str | None = None) -> dict:
    return await services.planning.get_context(week_start)


@router.get("/api/feedback")
async def get_feedback(
    services: WebServices,
    recipe_id: str | None = None,
    week_start: str | None = None,
    tags: list[str] | None = Query(default=None),
    feedback_type: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    items = await services.feedback.list(recipe_id, week_start, tags, feedback_type, limit)
    return {"items": items, "count": len(items)}


@router.post("/api/feedback")
async def save_feedback(feedback: dict[str, Any], services: WebServices) -> dict:
    return await services.feedback.save(feedback)


@router.get("/api/what-worked")
async def get_what_worked(
    services: WebServices,
    week_start: str | None = None,
    tags: list[str] | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    return await services.feedback.what_worked(week_start, tags, limit)


@router.get("/api/memories")
async def get_household_memory(
    services: WebServices,
    include_inactive: bool = False,
    status_filter: str | None = Query(default=None, alias="status"),
    scope: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    items = await services.memory.list(include_inactive, status_filter, scope, limit)
    return {"items": items, "count": len(items)}


@router.post("/api/memories")
async def save_household_memory(memory: dict[str, Any], services: WebServices) -> dict:
    return await services.memory.save(memory)


@router.patch("/api/memories/{memory_id}")
async def review_household_memory(
    memory_id: str, payload: dict[str, Any], services: WebServices
) -> dict:
    return await services.memory.review(memory_id, payload.get("action", ""), payload.get("content"))


@router.get("/s/{token}", response_class=HTMLResponse, include_in_schema=False)
async def shared_recipe_page(token: str) -> HTMLResponse:
    try:
        share = await read_shared_recipe(token, get_settings())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Sharing is temporarily unavailable") from exc
    if not share:
        raise HTTPException(status_code=404, detail="Share not found or no longer available")
    return HTMLResponse(
        render_shared_recipe_page(share),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"},
    )


@router.post("/api/shares/{token}/save")
async def save_shared_recipe(token: str, services: WebServices) -> dict:
    share = await read_shared_recipe(token, get_settings())
    if not share:
        raise HTTPException(status_code=404, detail="Share not found or no longer available")
    return await services.food.copy_shared_recipe(token)
