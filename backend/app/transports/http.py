from __future__ import annotations

import asyncio
from html import escape
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID
from datetime import UTC, date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..application import MealPrepServices
from ..application.notifications import list_inbox, update_inbox
from ..application.nutrition import weekly_nutrition, with_weekly_nutrition
from ..auth import SupabaseTokenVerifier
from ..config import get_settings
from ..container import services_for_request
from ..infrastructure.repositories import SupabaseRepository
from ..sharing import read_shared_recipe, read_shared_food, render_shared_recipe_page, render_shared_meal_page


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
async def website_home() -> HTMLResponse:
    html = (STATIC_DIR / "landing.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{MCP_URL}}", escape(get_settings().mcp_resource_url)))


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
async def app_snapshot(
    services: WebServices, sections: str | None = None, week_start: date | None = None,
) -> dict:
    return await services.household.snapshot(
        sections=sections.split(",") if sections is not None else None,
        week_start=week_start.isoformat() if week_start else None,
    )


@router.get("/api/app/bootstrap")
async def app_bootstrap(services: WebServices, include_sections: bool = True) -> dict:
    """Allow a lightweight startup while preserving older browser clients."""
    repository = services.household.repository
    if isinstance(repository, SupabaseRepository):
        pending = await repository.rpc("pending_household_invitations")
        invitations = pending.get("invitations") or []
        if not pending.get("hasHousehold") and invitations:
            return {"needsInvitationReview": True, "pendingInvites": invitations}
        snapshot, access, memberships = await asyncio.gather(
            services.household.snapshot(sections=None if include_sections else []),
            repository.rpc("household_access"),
            repository.list_households(),
        )
        return {
            "snapshot": snapshot,
            "access": access,
            "memberships": memberships,
            "pendingInvites": invitations,
        }
    return {"snapshot": await services.household.snapshot(sections=None if include_sections else []), "pendingInvites": []}


@router.get("/api/notifications")
async def list_notifications(services: WebServices, archived: bool = False) -> dict:
    return await list_inbox(services.household.repository, archived)


@router.get("/api/circles")
async def list_circles(services: WebServices) -> dict:
    return await services.circles.list_circles()


@router.post("/api/circles")
async def create_circle(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.create_circle(payload.get("name"))


@router.post("/api/circles/{circle_id}/invitations")
async def invite_circle_friend(circle_id: UUID, payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.invite_friend(str(circle_id), payload.get("email"))


@router.post("/api/circles/{circle_id}/invitation-response")
async def respond_circle_invitation(circle_id: UUID, payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.respond_invitation(str(circle_id), payload.get("accept") is True)


@router.delete("/api/circles/{circle_id}/members/{user_id}")
async def remove_circle_friend(circle_id: UUID, user_id: str, services: WebServices) -> dict:
    return await services.circles.remove_friend(str(circle_id), user_id)


@router.post("/api/circles/{circle_id}/leave")
async def leave_circle(circle_id: UUID, services: WebServices) -> dict:
    return await services.circles.leave_circle(str(circle_id))


@router.get("/api/circle-shares")
async def list_circle_shares(services: WebServices, limit: int = 50, offset: int = 0,
                             kind: str | None = None, circle_id: str | None = None) -> dict:
    return await services.circles.list_shared_with_me(limit, offset, kind, circle_id)


@router.get("/api/circle-shares/{share_id}")
async def get_circle_share(share_id: UUID, services: WebServices) -> dict:
    return await services.circles.get_shared_item(str(share_id))


@router.post("/api/circles/{circle_id}/weeks")
async def share_week_to_circle(circle_id: UUID, payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.share_week(str(circle_id), payload.get("weekStart"), payload.get("expectedAudience"))


@router.post("/api/circles/{circle_id}/recipes")
async def share_recipe_to_circle(circle_id: UUID, payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.share_recipe(str(circle_id), payload.get("recipeId"))


@router.post("/api/circles/{circle_id}/messages")
async def send_circle_message(circle_id: UUID, payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.send_message(str(circle_id), payload.get("body"),
        payload.get("attachmentKind"), payload.get("attachmentId"), payload.get("mentionIds"),
        payload.get("expectedAudience"))


@router.get("/api/circles/{circle_id}/mention-candidates")
async def circle_mention_candidates(circle_id: UUID, services: WebServices) -> dict:
    return await services.circles.mention_candidates(str(circle_id))


@router.get("/api/direct-shares")
async def list_direct_shares(services: WebServices, limit: int = 50, offset: int = 0) -> dict:
    return await services.circles.list_direct_shares(limit, offset)


@router.post("/api/direct-shares")
async def create_direct_share(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.share_direct(payload.get("email"), payload.get("kind"),
                                               payload.get("recipeId"), payload.get("weekStart"), payload.get("mealId"))


@router.post("/api/circle-shares/{share_id}/comments")
async def comment_on_circle_share(share_id: UUID, payload: dict[str, Any], services: WebServices) -> dict:
    return await services.circles.comment(str(share_id), payload.get("body"), payload.get("targetType", "post"),
                                           payload.get("targetId"), payload.get("mentionIds"))


@router.delete("/api/circle-comments/{comment_id}")
async def delete_circle_comment(comment_id: UUID, services: WebServices) -> dict:
    return await services.circles.delete_comment(str(comment_id))


@router.post("/api/circle-shares/{share_id}/recipes/{recipe_id}/save")
async def save_circle_recipe(share_id: UUID, recipe_id: UUID, services: WebServices) -> dict:
    return await services.circles.save_shared_recipe(str(share_id), str(recipe_id))


@router.delete("/api/circle-shares/{share_id}")
async def revoke_circle_share(share_id: UUID, services: WebServices) -> dict:
    return await services.circles.revoke_share(str(share_id))


async def change_notification(services, notification_id, field, enabled):
    try:
        return await update_inbox(services.household.repository, str(notification_id), field, enabled)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.patch("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: UUID, services: WebServices, read: bool = True) -> dict:
    return await change_notification(services, notification_id, "read_at", read)


@router.patch("/api/notifications/{notification_id}/archive")
async def archive_notification(notification_id: UUID, services: WebServices, archived: bool = True) -> dict:
    return await change_notification(services, notification_id, "archived_at", archived)


@router.get("/api/household")
async def get_household(services: WebServices) -> dict:
    return await services.household.get_context()


@router.put("/api/meal-slots")
async def configure_meal_slots(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.household.configure_meal_slots(payload.get("slots"))


@router.get("/api/meals")
async def search_meals(services: WebServices, query: str = "", limit: int = 50, offset: int = 0) -> dict:
    return await services.planning.meals.search(query, limit, offset)


@router.put("/api/meals")
async def save_meal(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.meals.save(payload)


@router.post("/api/meals/from-plan")
async def save_planned_meal(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.save_planned_meal(payload.get("weekStart"), payload.get("itemId"),
                                                    payload.get("name"), payload.get("servings"))


@router.get("/api/meals/{meal_id}")
async def get_meal(meal_id: str, services: WebServices) -> dict:
    return await services.planning.meals.get(meal_id)


@router.delete("/api/meals/{meal_id}")
async def archive_meal(meal_id: str, services: WebServices) -> dict:
    return await services.planning.meals.archive(meal_id)


@router.post("/api/meals/{meal_id}/plan")
async def plan_saved_meal(meal_id: str, payload: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.plan_saved_meal(payload.get("weekStart"), meal_id, payload.get("date"),
                                                  payload.get("slot"), payload.get("servings"))


@router.patch("/api/meal-plan/items")
async def update_plan_item(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.update_plan_item(payload.get("weekStart"), payload.get("kind"), payload.get("item", {}))


@router.post("/api/meal-plan/complete")
async def complete_plan_item(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.complete_item(payload.get("weekStart"), payload.get("kind"), payload.get("itemId"),
                                                  payload.get("inputs"), payload.get("outputs"))


@router.get("/api/meal-plan/shopping-preview")
async def preview_plan_shopping(week_start: str, services: WebServices) -> dict:
    return await services.planning.preview_shopping(week_start)


@router.post("/api/meal-plan/shopping")
async def save_plan_shopping(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.planning.save_plan_shopping(payload.get("weekStart"))


@router.post("/api/shopping-list/receive")
async def receive_shopping_item(payload: dict[str, Any], services: WebServices) -> dict:
    return await services.shopping.receive_item(payload.get("itemId"), payload.get("quantity"), payload.get("unit"),
                                                payload.get("storageLocation", "pantry"))


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


@router.get("/api/recipe-graph")
async def get_recipe_graph(
    services: WebServices, query: str = "", cuisine: list[str] = Query([]),
    goal: list[str] = Query([]), meal: list[str] = Query([]), diet: list[str] = Query([]),
    tag: list[str] = Query([]), max_minutes: int | None = None,
) -> dict:
    return await services.food.get_recipe_graph(query, {
        "cuisine": cuisine, "goal": goal, "meal": meal, "diet": diet, "tag": tag,
    }, max_minutes)


@router.get("/api/recipe-library")
async def browse_recipe_library(
    services: WebServices, query: str = "", cuisine: list[str] = Query([]),
    goal: list[str] = Query([]), meal: list[str] = Query([]), diet: list[str] = Query([]),
    tag: list[str] = Query([]), max_minutes: int | None = None,
    limit: int = 25, offset: int = 0, item_type: str = "recipes",
) -> dict:
    return await services.food.browse_recipe_library(query, {
        "cuisine": cuisine, "goal": goal, "meal": meal, "diet": diet, "tag": tag,
    }, max_minutes, limit, offset, item_type)


@router.put("/api/recipe-relationships")
async def save_recipe_relationship(relationship: dict[str, Any], services: WebServices) -> dict:
    return await services.food.save_recipe_relationship(relationship)


@router.delete("/api/recipe-relationships/{relationship_id:path}")
async def delete_recipe_relationship(relationship_id: str, services: WebServices) -> dict:
    return await services.food.delete_recipe_relationship(relationship_id)


@router.get("/api/recipes/{recipe_id}")
async def get_recipe(recipe_id: str, services: WebServices, variation: str | None = None) -> dict:
    return await services.food.get_recipe(recipe_id, variation)


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


@router.post("/api/meals/{meal_id}/shares")
async def create_meal_share(meal_id: UUID, services: WebServices) -> dict:
    share = await services.food.create_meal_share(str(meal_id))
    return {**share, "url": f"{get_settings().app_base_url.rstrip('/')}/s/{share['token']}"}


@router.get("/api/public-shares")
async def list_public_shares(services: WebServices) -> dict:
    items = await services.food.list_public_shares()
    base = get_settings().app_base_url.rstrip('/')
    return {"items": [{**item, "url": f"{base}/s/{item['token']}" if item.get("token") else None}
                      for item in items], "count": len(items)}


@router.delete("/api/public-shares/{share_id}")
async def revoke_public_share(share_id: UUID, services: WebServices) -> dict:
    return await services.food.revoke_public_share(str(share_id))


@router.get("/api/recipes/{recipe_id}/lessons")
async def get_recipe_lessons(recipe_id: str, services: WebServices, limit: int = 50) -> dict:
    return await services.feedback.recipe_feedback_summary(recipe_id, limit)


@router.get("/api/pantry")
async def get_pantry(services: WebServices) -> dict:
    items = await services.food.get_pantry()
    return {"items": items, "count": len(items)}


@router.get("/api/pantry/evidence")
async def get_pantry_evidence(
    services: WebServices,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    photos = await services.food.get_pantry_photos(limit + 1, offset)
    items = photos[:limit]
    return {
        "items": items,
        "count": len(items),
        "hasMore": len(photos) > limit,
        "nextOffset": offset + len(items),
    }


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
    plan = await services.planning.get_meal_plan(week_start)
    return {"plan": plan, "nutritionSummary": weekly_nutrition(plan)}


@router.get("/api/meal-plan/nutrition")
async def get_weekly_nutrition(services: WebServices, week_start: str | None = None, variation: str | None = None) -> dict:
    return await services.planning.get_weekly_nutrition(week_start, variation)


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
        share = await read_shared_food(token, get_settings())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Sharing is temporarily unavailable") from exc
    if not share:
        raise HTTPException(status_code=404, detail="Share not found or no longer available")
    return HTMLResponse(
        render_shared_meal_page(share) if share["kind"] == "meal" else render_shared_recipe_page(share),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"},
    )


@router.post("/api/shares/{token}/save")
async def save_shared_recipe(token: str, services: WebServices) -> dict:
    share = await read_shared_recipe(token, get_settings())
    if not share:
        raise HTTPException(status_code=404, detail="Share not found or no longer available")
    return await services.food.copy_shared_recipe(token)
