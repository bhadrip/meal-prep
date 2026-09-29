from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from ..auth import SupabaseTokenVerifier
from ..config import MCP_AUTH_SCOPES, get_settings
from ..container import services_for_request


settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
MEAL_PLAN_UI_URI = "ui://meal-prep/meal-plan-v2.html"
SHOPPING_UI_URI = "ui://meal-prep/shopping-list-v2.html"
HOUSEHOLD_UI_URI = "ui://meal-prep/household-snapshot-v2.html"
ONBOARDING_UI_URI = "ui://meal-prep/onboarding-v2.html"

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
        "Call get_planning_context before drafting or revising a weekly meal plan. It returns household "
        "preferences, the requested or remembered weekly schedule, the relevant retrospective, recent "
        "experience feedback, and active "
        "household memories. If onboardingComplete is false, call render_onboarding so the user can complete "
        "the MCP-served setup for household size, dietary restrictions, store priority, weeknight cooking limit, "
        "lunch leftovers, and the planning areas they want coordinated. Save those areas in "
        "planningPreferences.focusAreas. Do not describe empty or null onboarding "
        "fields as saved preferences. Respect hard dietary restrictions. "
        "Do not assume a weekly plan is dinner-only. Give each saved entry an explicit slot such as breakfast, "
        "lunch, snack, dinner, or prep, and keep repeated breakfasts and packed lunches simple unless variety is requested. "
        "Use confirmed memories as preferences; treat suggested memories, retrospectives, and feedback only as evidence. "
        "When someone reports how a dish or week went, save atomic feedback linked to the meal occurrence, recipe, "
        "and week whenever those subjects are known. Use canonical tags for reusable themes and audiences, preserve "
        "an actionable nextTime, and query recipe lessons before repeating a dish. "
        "A null schedule or retrospective means no record exists, not permission to invent one. "
        "Search stores in storePriority order. Save durable plans and lists only after the user agrees. "
        "When the user asks what Meal Prep knows, use render_household_snapshot so the result is "
        "a compact interactive view instead of a long text inventory. "
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


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_household_context() -> dict[str, Any]:
    """Load household size, restrictions, preferred stores, and planning preferences before planning."""
    return await services_for_request().household.get_context()


@mcp.tool(annotations=WRITE, structured_output=True)
async def update_household_preferences(
    household_size: int | None = None,
    dietary_restrictions: list[str] | None = None,
    store_priority: list[dict[str, Any]] | None = None,
    planning_preferences: dict[str, Any] | None = None,
    complete_onboarding: bool = False,
) -> dict[str, Any]:
    """Update explicit preferences; complete onboarding only after the user answers every setup question."""
    return await services_for_request().household.update_preferences(
        household_size=household_size,
        dietary_restrictions=dietary_restrictions,
        store_priority=store_priority,
        planning_preferences=planning_preferences,
        complete_onboarding=complete_onboarding,
    )


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def search_recipes(query: str = "", limit: int = 10) -> dict[str, Any]:
    """Search the household recipe library without changing it."""
    items = await services_for_request().food.search_recipes(query=query, limit=limit)
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_recipe(recipe_id: str) -> dict[str, Any]:
    """Get one recipe by its UUID."""
    return await services_for_request().food.get_recipe(recipe_id)


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Create or update a normalized household recipe with provenance fields when available."""
    return await services_for_request().food.save_recipe(recipe)


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def archive_recipe(recipe_id: str) -> dict[str, Any]:
    """Archive a recipe after the user has confirmed the removal."""
    return await services_for_request().food.archive_recipe(recipe_id)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_pantry() -> dict[str, Any]:
    """Return pantry items with quantity confidence and freshness basis."""
    items = await services_for_request().food.get_pantry()
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def update_pantry_item(item: dict[str, Any]) -> dict[str, Any]:
    """Create or update one pantry item. Never invent an exact expiry date."""
    return await services_for_request().food.update_pantry_item(item)


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_meal_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Persist an approved weekly plan whose entries identify breakfast, lunch, snack, dinner, or prep slots."""
    return await services_for_request().planning.save_meal_plan(plan)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_meal_plan(week_start: str | None = None) -> dict[str, Any]:
    """Return the meal plan for a week, or the latest plan when no week is supplied."""
    plan = await services_for_request().planning.get_meal_plan(week_start)
    return {"plan": plan}


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_shopping_list(shopping_list: dict[str, Any]) -> dict[str, Any]:
    """Persist a shopping list grouped by preferred store. This does not place an order."""
    return await services_for_request().shopping.save(shopping_list)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_shopping_list(list_id: str | None = None) -> dict[str, Any]:
    """Return one shopping list or the latest active list."""
    value = await services_for_request().shopping.get(list_id)
    return {"shoppingList": value}


@mcp.tool(annotations=WRITE, structured_output=True)
async def mark_item_purchased(
    item_id: str,
    purchased: bool = True,
    purchased_quantity: float | None = None,
) -> dict[str, Any]:
    """Mark a shopping item purchased or unpurchased. This does not place an order."""
    return await services_for_request().shopping.mark_purchased(item_id, purchased, purchased_quantity)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_weekly_schedule(week_start: str | None = None) -> dict[str, Any]:
    """Return the requested weekly rhythm, or the latest remembered schedule."""
    return {"schedule": await services_for_request().planning.get_schedule(week_start)}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_planning_context(week_start: str | None = None) -> dict[str, Any]:
    """Load the complete durable context needed before drafting or revising a weekly meal plan."""
    return await services_for_request().planning.get_context(week_start)


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_weekly_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    """Save an explicitly confirmed seven-day planning rhythm for one week."""
    return await services_for_request().planning.save_schedule(schedule)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_latest_retro() -> dict[str, Any]:
    """Return the most recent weekly reflection as planning evidence, if one exists."""
    return {"retro": await services_for_request().planning.get_latest_retro()}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_weekly_retro(week_start: str | None = None) -> dict[str, Any]:
    """Return a retrospective for one week, or the latest retrospective when no week is supplied."""
    return {"retro": await services_for_request().planning.get_retro(week_start)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_weekly_retro(retro: dict[str, Any]) -> dict[str, Any]:
    """Save a weekly reflection. Do not promote its observations to durable preferences automatically."""
    return await services_for_request().planning.save_retro(retro)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_feedback(
    recipe_id: str | None = None,
    week_start: str | None = None,
    tags: list[str] | None = None,
    feedback_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Traverse experience feedback by recipe, week, canonical tags, or outcome type."""
    items = await services_for_request().feedback.list(
        recipe_id, week_start, tags, feedback_type, limit
    )
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    """Save one observation and its graph links to an occurrence, recipe or variant, week, and canonical tags."""
    return await services_for_request().feedback.save(feedback)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_what_worked(
    week_start: str | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent successful meal experiences, optionally filtered by week or canonical tags."""
    return await services_for_request().feedback.what_worked(week_start, tags, limit)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_recipe_lessons(recipe_id: str, limit: int = 50) -> dict[str, Any]:
    """Summarize what worked, next-time corrections, tags, and successful variants for one recipe."""
    return await services_for_request().feedback.recipe_lessons(recipe_id, limit)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_household_memory(
    include_inactive: bool = False,
    status: str | None = None,
    scope: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List visible household memories with source, review status, scope, and evidence count."""
    items = await services_for_request().memory.list(include_inactive, status, scope, limit)
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_household_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Save a reviewable suggestion by default; use confirmed only for an explicit user instruction."""
    return await services_for_request().memory.save(memory)


@mcp.tool(annotations=WRITE, structured_output=True)
async def review_household_memory(memory_id: str, action: str, content: str | None = None) -> dict[str, Any]:
    """Confirm, correct, or forget one visible memory after the user requests that action."""
    return await services_for_request().memory.review(memory_id, action, content)


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": HOUSEHOLD_UI_URI}},
    structured_output=True,
)
async def render_household_snapshot() -> dict[str, Any]:
    """Render a compact in-chat view of household rules, pantry, schedule, saved data, and memory."""
    snapshot = await services_for_request().household.snapshot()
    return {"kind": "household_snapshot", **snapshot}


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": ONBOARDING_UI_URI}},
    structured_output=True,
)
async def render_onboarding() -> dict[str, Any]:
    """Render household setup for meals, prep, pantry, and shopping."""
    household = await services_for_request().household.get_context()
    return {"kind": "onboarding", "household": household}


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": MEAL_PLAN_UI_URI}},
    structured_output=True,
)
async def render_meal_plan(week_start: str | None = None) -> dict[str, Any]:
    """Render the final meal plan. Call get_meal_plan first when reasoning over the plan."""
    plan = await services_for_request().planning.get_meal_plan(week_start)
    return {"kind": "meal_plan", "plan": plan}


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": SHOPPING_UI_URI}},
    structured_output=True,
)
async def render_shopping_list(list_id: str | None = None) -> dict[str, Any]:
    """Render the final grouped shopping checklist. Call get_shopping_list first when reasoning over it."""
    value = await services_for_request().shopping.get(list_id)
    return {"kind": "shopping_list", "shoppingList": value}


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


@mcp.resource(
    HOUSEHOLD_UI_URI,
    name="household-snapshot-ui",
    title="Household meal-prep snapshot",
    description="A compact, tabbed view of household rules and saved meal-prep data.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def household_snapshot_resource() -> str:
    return (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")


@mcp.resource(
    ONBOARDING_UI_URI,
    name="onboarding-ui",
    title="Household food planning setup",
    description="Set up the household food week across meals, prep, pantry, and shopping.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def onboarding_resource() -> str:
    return (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")


mcp_app = mcp.streamable_http_app()
