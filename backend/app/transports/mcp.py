from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from ..auth import SupabaseTokenVerifier
from ..config import MCP_AUTH_SCOPES, get_settings
from ..container import services_for_request


settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
MEAL_PLAN_UI_URI = "ui://meal-prep/meal-plan-v2.html"
SHOPPING_UI_URI = "ui://meal-prep/shopping-list-v2.html"
HOUSEHOLD_UI_URI = "ui://meal-prep/household-dashboard-v4.html"
ONBOARDING_UI_URI = "ui://meal-prep/onboarding-v2.html"
RECIPE_LIBRARY_UI_URI = "ui://meal-prep/recipe-library-v1.html"
FEEDBACK_UI_URI = "ui://meal-prep/feedback-v2.html"
PANTRY_EVIDENCE_UI_URI = "ui://meal-prep/pantry-evidence-v1.html"


class ChatGPTPhotoFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    download_url: str
    file_id: str
    mime_type: str = ""
    file_name: str = ""

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
        "An account may belong to several households. Call list_households when the user names a household "
        "or the intended household is unclear; use switch_household before reading or changing that household. "
        "The active household is shared by the website and MCP. Never mix data from different households. "
        "Call get_planning_context before drafting or revising a weekly meal plan. It returns household "
        "preferences, the requested or remembered weekly schedule, recent feedback, and active "
        "household knowledge. If onboardingComplete is false, call render_onboarding so the user can complete "
        "the MCP-served setup for household size, dietary restrictions, store priority, weeknight cooking limit, "
        "lunch leftovers, and the planning areas they want coordinated. Save those areas in "
        "planningPreferences.focusAreas. Do not describe empty or null onboarding "
        "fields as saved preferences. Respect hard dietary restrictions. "
        "Do not assume a weekly plan is dinner-only. Give each saved entry an explicit slot such as breakfast, "
        "lunch, snack, dinner, or prep, and keep repeated breakfasts and packed lunches simple unless variety is requested. "
        "Use confirmed household knowledge as preferences; treat suggestions and feedback only as evidence. "
        "When someone reports how a dish or week went, save atomic feedback linked to the meal occurrence, recipe, "
        "and week whenever those subjects are known. Use canonical tags for reusable themes and audiences, preserve "
        "an actionable nextTime, and query the recipe feedback summary before repeating a dish. A weekly check-in "
        "is a conversation that creates ordinary feedback entries; it is not a separate data type. "
        "A null schedule means no record exists, not permission to invent one. "
        "Search stores in storePriority order. When someone adds a shopping item, ask which store they generally buy it at; "
        "the store is optional and belongs to that item. Save durable plans and lists only after the user agrees. "
        "When the user asks what Meal Prep knows, use render_household_snapshot so the result is "
        "a compact card dashboard instead of a long text inventory. When the user asks to change that "
        "dashboard, use get_dashboard_layout and configure_dashboard, then render it again for verification. "
        "When the user asks to see, browse, or list saved recipes, use render_recipe_library so the recipes "
        "appear as visual cards with expandable ingredients and instructions instead of a text list. "
        "When the user asks to share a saved recipe, use create_recipe_share and return its URL. "
        "Anyone with that link can view a fixed recipe snapshot. Use list_recipe_shares and "
        "revoke_recipe_share when they ask to stop sharing. A recipient can save an independent "
        "copy with copy_shared_recipe. "
        "When the user asks for a weekly check-in, what worked, or meal feedback, use render_feedback "
        "so feedback appears separately from confirmed household preferences. "
        "Never place or imply an order; external commerce requires a separate confirmation flow. "
        "When the user attaches a fridge or pantry photo and asks to update the pantry, "
        "call save_pantry_photo with the file parameter and visible observed_items. "
        "Use apply_to_pantry=false if they want a list before deciding what to save. "
        "Do not mark visual quantities exact or invent expiry dates. "
        "Use render_pantry_evidence when they want to review saved pantry photos."
        " When someone says they used pantry food, call record_pantry_use with the amount used; "
        "include a saved recipe ID or a meal title when they identify the meal. "
        "The amount is subtracted from the pantry quantity, so never pass the remaining amount as quantity."
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
APPEND = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
ARCHIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
SHARE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_household_context() -> dict[str, Any]:
    """Load household size, restrictions, preferred stores, and planning preferences before planning."""
    return await services_for_request().household.get_context()


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_households() -> dict[str, Any]:
    """List households this account belongs to and identify the active household."""
    return await services_for_request().household.list_households()


@mcp.tool(annotations=WRITE, structured_output=True)
async def switch_household(household_id: str) -> dict[str, Any]:
    """Select a household by ID for subsequent website and MCP planning actions."""
    return await services_for_request().household.switch_household(household_id)


@mcp.tool(annotations=APPEND, structured_output=True)
async def create_household(name: str) -> dict[str, Any]:
    """Create another household owned by this account and make it active."""
    return await services_for_request().household.create_household(name)


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
async def get_dashboard_layout() -> dict[str, Any]:
    """Return the dashboard card order, hidden cards, and valid card IDs without changing anything."""
    return await services_for_request().household.get_dashboard_layout()


@mcp.tool(annotations=WRITE, structured_output=True)
async def configure_dashboard(
    card_order: list[str] | None = None,
    hidden_cards: list[str] | None = None,
    reset_to_default: bool = False,
) -> dict[str, Any]:
    """Configure the dashboard from chat; prioritized card IDs move first, omitted values stay unchanged, and reset restores the shared starting template."""
    return await services_for_request().household.configure_dashboard(
        card_order=card_order,
        hidden_cards=hidden_cards,
        reset_to_default=reset_to_default,
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


@mcp.tool(annotations=SHARE, structured_output=True)
async def create_recipe_share(recipe_id: str, expires_at: str | None = None) -> dict[str, Any]:
    """Publish an explicit snapshot of one household recipe to a revocable link. Only call when the user asks to share it. The URL can be opened by anyone holding it."""
    share = await services_for_request().food.create_recipe_share(recipe_id, expires_at)
    return {**share, "url": f"{settings.app_base_url.rstrip('/')}/s/{share['token']}"}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_recipe_shares() -> dict[str, Any]:
    """List links created by the caller, including expired and revoked links. Raw link tokens are never returned again."""
    items = await services_for_request().food.list_recipe_shares()
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def revoke_recipe_share(share_id: str) -> dict[str, Any]:
    """Revoke a recipe link created by the caller so it can no longer be opened or copied."""
    return await services_for_request().food.revoke_recipe_share(share_id)


@mcp.tool(annotations=WRITE, structured_output=True)
async def copy_shared_recipe(token: str) -> dict[str, Any]:
    """Save an independent copy of a shared recipe into the caller's household."""
    return await services_for_request().food.copy_shared_recipe(token)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_pantry() -> dict[str, Any]:
    """Return pantry items with category, quantity confidence, and freshness basis. Categories are fruits, vegetables, snacks, frozen, dry_goods, condiments, and uncategorized."""
    items = await services_for_request().food.get_pantry()
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def update_pantry_item(item: dict[str, Any]) -> dict[str, Any]:
    """Create or update one pantry item. Set category to fruits, vegetables, snacks, frozen, dry_goods, condiments, or uncategorized when known; unclear items remain uncategorized. Never invent an exact expiry date."""
    return await services_for_request().food.update_pantry_item(item)


@mcp.tool(annotations=APPEND, structured_output=True)
async def record_pantry_use(
    item_id: str, quantity: float, recipe_id: str | None = None,
    meal_title: str | None = None,
) -> dict[str, Any]:
    """Subtract a used amount from one pantry item. Optionally link a saved recipe and/or name the meal. First use get_pantry to find the item ID and its unit; quantity is the amount used in that unit."""
    return await services_for_request().food.record_pantry_use(item_id, quantity, recipe_id, meal_title)


@mcp.tool(annotations=APPEND, meta={"openai/fileParams": ["file"]}, structured_output=True)
async def save_pantry_photo(
    file: ChatGPTPhotoFile,
    observed_items: list[dict[str, Any]],
    storage_location: str = "fridge",
    note: str = "",
    apply_to_pantry: bool = True,
) -> dict[str, Any]:
    """Store a compact copy of an attached ChatGPT photo and observed items; optionally apply them to the pantry."""
    return await services_for_request().food.save_pantry_photo(
        file.model_dump(exclude_none=True), observed_items, storage_location, note, apply_to_pantry
    )


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_pantry_evidence(limit: int = 30) -> dict[str, Any]:
    """List saved pantry photos, observations, applied item IDs, and temporary private image links."""
    photos = await services_for_request().food.get_pantry_photos(limit)
    return {"photos": photos, "count": len(photos)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def apply_pantry_evidence(evidence_id: str, observed_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Apply a previously captured pantry photo after review, with optional corrected items."""
    return await services_for_request().food.apply_pantry_photo(evidence_id, observed_items)


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
    """Persist a shopping list. Each item may have an optional store tag. This does not place an order."""
    return await services_for_request().shopping.save(shopping_list)


@mcp.tool(annotations=APPEND, structured_output=True)
async def add_shopping_item(item: dict[str, Any], list_id: str | None = None) -> dict[str, Any]:
    """Add one item to a shopping list, creating a list if needed. Ask for the optional store generally used for this item; pass it as item.store. This does not place an order."""
    return await services_for_request().shopping.add_item(item, list_id)


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
async def get_feedback(
    recipe_id: str | None = None,
    week_start: str | None = None,
    tags: list[str] | None = None,
    feedback_type: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Find feedback by recipe, week, reusable tags, or outcome type."""
    items = await services_for_request().feedback.list(
        recipe_id, week_start, tags, feedback_type, limit
    )
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    """Save one piece of feedback about a meal, recipe or variant, or week."""
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
async def get_recipe_feedback_summary(recipe_id: str, limit: int = 50) -> dict[str, Any]:
    """Summarize what worked, next-time changes, problems, and successful variants for one recipe."""
    return await services_for_request().feedback.recipe_feedback_summary(recipe_id, limit)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_household_memory(
    include_inactive: bool = False,
    status: str | None = None,
    scope: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List confirmed household preferences and suggestions that still need confirmation."""
    items = await services_for_request().memory.list(include_inactive, status, scope, limit)
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_household_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Save a household suggestion; mark it confirmed only after an explicit user instruction."""
    return await services_for_request().memory.save(memory)


@mcp.tool(annotations=WRITE, structured_output=True)
async def review_household_memory(memory_id: str, action: str, content: str | None = None) -> dict[str, Any]:
    """Confirm, correct, or forget one household suggestion after the user requests that action."""
    return await services_for_request().memory.review(memory_id, action, content)


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": HOUSEHOLD_UI_URI}},
    structured_output=True,
)
async def render_household_snapshot() -> dict[str, Any]:
    """Render the chat-configured card dashboard of household rules, pantry, schedule, saved data, and preferences."""
    snapshot = await services_for_request().household.snapshot()
    return {"kind": "household_snapshot", **snapshot}


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": RECIPE_LIBRARY_UI_URI}},
    structured_output=True,
)
async def render_recipe_library(query: str = "", limit: int = 50) -> dict[str, Any]:
    """Render saved recipes as a visual library with expandable recipe details."""
    recipes = await services_for_request().food.search_recipes(query=query, limit=limit)
    return {"kind": "recipe_library", "recipes": recipes, "query": query, "count": len(recipes)}


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": FEEDBACK_UI_URI}},
    structured_output=True,
)
async def render_feedback() -> dict[str, Any]:
    """Render saved meal and week feedback separately from confirmed household preferences."""
    snapshot = await services_for_request().household.snapshot()
    return {
        "kind": "feedback",
        "sections": {"feedback": snapshot["sections"]["feedback"]},
    }


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": PANTRY_EVIDENCE_UI_URI}},
    structured_output=True,
)
async def render_pantry_evidence(limit: int = 30) -> dict[str, Any]:
    """Render saved pantry photo evidence as reviewable image cards."""
    photos = await services_for_request().food.get_pantry_photos(limit)
    return {"kind": "pantry_evidence", "photos": photos, "count": len(photos)}


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
    name="household-dashboard-ui",
    title="Household meal-prep dashboard",
    description="A chat-configured card dashboard of household rules and saved meal-prep data.",
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


@mcp.resource(
    RECIPE_LIBRARY_UI_URI,
    name="recipe-library-ui",
    title="Recipe library",
    description="A visual, searchable library of saved household recipes.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def recipe_library_resource() -> str:
    return (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")


@mcp.resource(
    FEEDBACK_UI_URI,
    name="feedback-ui",
    title="Meal and week feedback",
    description="Saved feedback about meals, recipes, and weekly planning.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def feedback_resource() -> str:
    return (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")


@mcp.resource(
    PANTRY_EVIDENCE_UI_URI,
    name="pantry-evidence-ui",
    title="Pantry photo evidence",
    description="Review compact saved pantry photos and the items observed in each.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True, "csp": {"resourceDomains": [settings.supabase_url.rstrip('/')] if settings.supabase_url else []}}},
)
def pantry_evidence_resource() -> str:
    return (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")


mcp_app = mcp.streamable_http_app()
