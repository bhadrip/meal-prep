from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .auth import SupabaseTokenVerifier
from .config import MCP_AUTH_SCOPES, get_settings
from .db import RepositoryError, repository_for_request


settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"
MEAL_PLAN_UI_URI = "ui://meal-prep/meal-plan-v1.html"
SHOPPING_UI_URI = "ui://meal-prep/shopping-list-v1.html"

auth_settings = None
token_verifier = None
app_url = urlparse(settings.app_base_url)
if settings.auth_required and settings.supabase_configured:
    auth_settings = AuthSettings(
        issuer_url=settings.supabase_auth_issuer,
        resource_server_url=settings.mcp_resource_url,
        required_scopes=list(MCP_AUTH_SCOPES),
        validate_token_resource=False,
    )
    token_verifier = SupabaseTokenVerifier(settings)

mcp = FastMCP(
    "meal-prep",
    instructions=(
        "Load get_household_context before planning. If onboardingComplete is false, ask the user "
        "for household size, dietary restrictions, store priority, weeknight cooking limit, and "
        "whether dinner should provide lunch leftovers. Do not describe empty or null onboarding "
        "fields as saved preferences. Respect hard dietary restrictions. "
        "Load the weekly schedule and any prior retrospective before drafting a new plan. "
        "Search stores in storePriority order. Save durable plans and lists only after the user agrees. "
        "Never place or imply an order; external commerce requires a separate confirmation flow."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    auth=auth_settings,
    token_verifier=token_verifier,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            app_url.netloc,
            "localhost:*",
            "127.0.0.1:*",
            "testserver",
        ],
        allowed_origins=[f"{app_url.scheme}://{app_url.netloc}"],
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
ARCHIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


def _repo():
    return repository_for_request()


def _error(exc: RepositoryError) -> ValueError:
    return ValueError(str(exc))


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_household_context() -> dict[str, Any]:
    """Load household size, restrictions, preferred stores, and planning preferences before planning."""
    try:
        return await _repo().get_household_context()
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def update_household_preferences(
    household_size: int | None = None,
    dietary_restrictions: list[str] | None = None,
    store_priority: list[dict[str, Any]] | None = None,
    planning_preferences: dict[str, Any] | None = None,
    complete_onboarding: bool = False,
) -> dict[str, Any]:
    """Update explicit preferences; complete onboarding only after the user answers every setup question."""
    if complete_onboarding:
        missing = []
        if household_size is None:
            missing.append("household_size")
        if dietary_restrictions is None:
            missing.append("dietary_restrictions")
        if store_priority is None:
            missing.append("store_priority")
        if planning_preferences is None or "weeknightMaxMinutes" not in planning_preferences:
            missing.append("planning_preferences.weeknightMaxMinutes")
        if planning_preferences is None or "leftoversForLunch" not in planning_preferences:
            missing.append("planning_preferences.leftoversForLunch")
        if missing:
            raise ValueError(f"Cannot complete onboarding; missing: {', '.join(missing)}")
    patch = {
        key: value
        for key, value in {
            "householdSize": household_size,
            "dietaryRestrictions": dietary_restrictions,
            "storePriority": store_priority,
            "planningPreferences": planning_preferences,
        }.items()
        if value is not None
    }
    if complete_onboarding:
        patch["onboardingCompletedAt"] = datetime.now(UTC).isoformat()
    try:
        return await _repo().update_household_preferences(patch)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def search_recipes(query: str = "", limit: int = 10) -> dict[str, Any]:
    """Search the household recipe library without changing it."""
    try:
        items = await _repo().search_recipes(query=query, limit=limit)
        return {"items": items, "count": len(items)}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_recipe(recipe_id: str) -> dict[str, Any]:
    """Get one recipe by its UUID."""
    try:
        item = await _repo().get_recipe(recipe_id)
        if not item:
            raise ValueError("Recipe was not found")
        return item
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Create or update a normalized household recipe with provenance fields when available."""
    if not str(recipe.get("title", "")).strip():
        raise ValueError("recipe.title is required")
    try:
        return await _repo().save_recipe(recipe)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def archive_recipe(recipe_id: str) -> dict[str, Any]:
    """Archive a recipe after the user has confirmed the removal."""
    try:
        return await _repo().archive_recipe(recipe_id)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_pantry() -> dict[str, Any]:
    """Return pantry items with quantity confidence and freshness basis."""
    try:
        items = await _repo().get_pantry()
        return {"items": items, "count": len(items)}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def update_pantry_item(item: dict[str, Any]) -> dict[str, Any]:
    """Create or update one pantry item. Never invent an exact expiry date."""
    if not str(item.get("name", "")).strip():
        raise ValueError("item.name is required")
    try:
        return await _repo().update_pantry_item(item)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_meal_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Persist a weekly meal plan and its entries after the user approves the draft."""
    if not plan.get("weekStart") or not isinstance(plan.get("entries"), list):
        raise ValueError("plan.weekStart and plan.entries are required")
    try:
        return await _repo().save_meal_plan(plan)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_meal_plan(week_start: str | None = None) -> dict[str, Any]:
    """Return the meal plan for a week, or the latest plan when no week is supplied."""
    try:
        plan = await _repo().get_meal_plan(week_start)
        return {"plan": plan}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_shopping_list(shopping_list: dict[str, Any]) -> dict[str, Any]:
    """Persist a shopping list grouped by preferred store. This does not place an order."""
    if not isinstance(shopping_list.get("items"), list):
        raise ValueError("shopping_list.items is required")
    try:
        return await _repo().save_shopping_list(shopping_list)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_shopping_list(list_id: str | None = None) -> dict[str, Any]:
    """Return one shopping list or the latest active list."""
    try:
        value = await _repo().get_shopping_list(list_id)
        return {"shoppingList": value}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def mark_item_purchased(
    item_id: str,
    purchased: bool = True,
    purchased_quantity: float | None = None,
) -> dict[str, Any]:
    """Mark a shopping item purchased or unpurchased. This does not place an order."""
    try:
        return await _repo().mark_item_purchased(item_id, purchased, purchased_quantity)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_weekly_schedule(week_start: str | None = None) -> dict[str, Any]:
    """Return the requested weekly rhythm, or the latest remembered schedule."""
    try:
        return {"schedule": await _repo().get_weekly_schedule(week_start)}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_weekly_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    """Save an explicitly confirmed seven-day planning rhythm for one week."""
    if not schedule.get("weekStart") or len(schedule.get("days", [])) != 7:
        raise ValueError("schedule.weekStart and seven schedule.days are required")
    try:
        return await _repo().save_weekly_schedule(schedule)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_latest_retro() -> dict[str, Any]:
    """Return the most recent weekly reflection as planning evidence, if one exists."""
    try:
        return {"retro": await _repo().get_latest_retro()}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_weekly_retro(retro: dict[str, Any]) -> dict[str, Any]:
    """Save a weekly reflection. Do not promote its observations to durable preferences automatically."""
    if not retro.get("weekStart") or not isinstance(retro.get("outcomes", []), list):
        raise ValueError("retro.weekStart and retro.outcomes are required")
    try:
        return await _repo().save_weekly_retro(retro)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_household_memory(include_inactive: bool = False) -> dict[str, Any]:
    """List visible household memories with source, review status, scope, and evidence count."""
    try:
        items = await _repo().get_household_memory(include_inactive)
        return {"items": items, "count": len(items)}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_household_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Save an explicit user memory or a reviewable suggestion with source provenance."""
    if not str(memory.get("content", "")).strip():
        raise ValueError("memory.content is required")
    try:
        return await _repo().save_household_memory(memory)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(annotations=WRITE, structured_output=True)
async def review_household_memory(memory_id: str, action: str, content: str | None = None) -> dict[str, Any]:
    """Confirm, correct, or forget one visible memory after the user requests that action."""
    if action not in {"confirm", "update", "forget"}:
        raise ValueError("action must be confirm, update, or forget")
    try:
        return await _repo().review_household_memory(memory_id, action, content)
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": MEAL_PLAN_UI_URI}},
    structured_output=True,
)
async def render_meal_plan(week_start: str | None = None) -> dict[str, Any]:
    """Render the final meal plan. Call get_meal_plan first when reasoning over the plan."""
    try:
        plan = await _repo().get_meal_plan(week_start)
        return {"kind": "meal_plan", "plan": plan}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": SHOPPING_UI_URI}},
    structured_output=True,
)
async def render_shopping_list(list_id: str | None = None) -> dict[str, Any]:
    """Render the final grouped shopping checklist. Call get_shopping_list first when reasoning over it."""
    try:
        value = await _repo().get_shopping_list(list_id)
        return {"kind": "shopping_list", "shoppingList": value}
    except RepositoryError as exc:
        raise _error(exc) from exc


@mcp.resource(
    MEAL_PLAN_UI_URI,
    name="meal-plan-ui",
    title="Meal plan calendar",
    description="A compact weekly meal-plan calendar.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def meal_plan_resource() -> str:
    return (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")


@mcp.resource(
    SHOPPING_UI_URI,
    name="shopping-list-ui",
    title="Shopping checklist",
    description="A shopping checklist grouped by store.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def shopping_list_resource() -> str:
    return (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")


mcp_app = mcp.streamable_http_app()
