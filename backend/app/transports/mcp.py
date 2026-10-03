from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from ..application.notifications import list_inbox, update_inbox
from ..application.nutrition import weekly_nutrition, with_weekly_nutrition
from ..auth import SupabaseTokenVerifier
from ..config import MCP_AUTH_SCOPES, get_settings
from ..container import services_for_request


settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def mcp_app_html() -> str:
    """MCP resources are self-contained because hosts need not allow static asset URLs."""
    html = (STATIC_DIR / "mcp-app.html").read_text(encoding="utf-8")
    for asset in ("recipe-graph", "recipe-browser", "nutrition"):
        css = (STATIC_DIR / f"{asset}.css").read_text(encoding="utf-8")
        script = (STATIC_DIR / f"{asset}.js").read_text(encoding="utf-8")
        html = html.replace(f'<link rel="stylesheet" href="/static/{asset}.css" />', f"<style>{css}</style>").replace(
            f'<script src="/static/{asset}.js"></script>', f"<script>{script}</script>")
    return html

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
    instructions=Path(__file__).with_name("meal-prep-instructions.md").read_text(encoding="utf-8"),
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
async def list_notifications(archived: bool = False) -> dict[str, Any]:
    """List your active inbox, or archived notifications when archived is true."""
    return await list_inbox(services_for_request().household.repository, archived)


@mcp.tool(annotations=WRITE, structured_output=True)
async def set_notification_read(notification_id: str, read: bool = True) -> dict[str, Any]:
    """Mark your notification read or unread without opening its destination."""
    return await update_inbox(services_for_request().household.repository, notification_id, "read_at", read)


@mcp.tool(annotations=WRITE, structured_output=True)
async def archive_notification(notification_id: str, archived: bool = True) -> dict[str, Any]:
    """Clear a notification from your inbox by archiving it, or restore it with archived=false."""
    return await update_inbox(services_for_request().household.repository, notification_id, "archived_at", archived)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_household_context() -> dict[str, Any]:
    """Load household size, restrictions, preferred stores, and planning preferences before planning."""
    return await services_for_request().household.get_context()


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_households() -> dict[str, Any]:
    """List households this account belongs to and identify the active household."""
    return await services_for_request().household.list_households()


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_circles() -> dict[str, Any]:
    """List private friend circles and pending invitations. Only accepted circles can be read or shared to."""
    return await services_for_request().circles.list_circles()


@mcp.tool(annotations=APPEND, structured_output=True)
async def create_circle(name: str) -> dict[str, Any]:
    """Create a private circle for close friends; the creator is its first member."""
    return await services_for_request().circles.create_circle(name)


@mcp.tool(annotations=SHARE, structured_output=True)
async def invite_circle_friend(circle_id: str, email: str) -> dict[str, Any]:
    """Invite an existing Meal Prep account into a private circle by email, with an in-app notification only."""
    return await services_for_request().circles.invite_friend(circle_id, email)


@mcp.tool(annotations=WRITE, structured_output=True)
async def respond_circle_invitation(circle_id: str, accept: bool) -> dict[str, Any]:
    """Accept or decline a friend circle invitation."""
    return await services_for_request().circles.respond_invitation(circle_id, accept)


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def remove_circle_friend(circle_id: str, user_id: str) -> dict[str, Any]:
    """Remove a friend from a circle you own; their access to its shares and circle notifications ends immediately."""
    return await services_for_request().circles.remove_friend(circle_id, user_id)


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def leave_circle(circle_id: str) -> dict[str, Any]:
    """Leave a circle you joined; its shares and notifications stop being visible."""
    return await services_for_request().circles.leave_circle(circle_id)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_shared_with_me(limit: int = 50, offset: int = 0, kind: str | None = None,
                              circle_id: str | None = None) -> dict[str, Any]:
    """Read accessible private conversations, including direct shares, with messages, shared weeks, recipes, and saved meals. Set circle_id for one conversation; page with limit/offset until nextOffset is null. Open an item to read its thread. No whole-plan copy."""
    return await services_for_request().circles.list_shared_with_me(limit, offset, kind, circle_id)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_direct_shares(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List one-to-one recipe and weekly-plan shares addressed to or created by this account, with thread counts. Page until nextOffset is null."""
    return await services_for_request().circles.list_direct_shares(limit, offset)


@mcp.tool(annotations=SHARE, structured_output=True)
async def share_direct(email: str, kind: str, recipe_id: str | None = None,
                       week_start: str | None = None, meal_id: str | None = None) -> dict[str, Any]:
    """Share one immutable recipe, saved meal, or whole-week snapshot directly with an existing account by email. kind is recipe, meal, or week. This does not add the friend to a circle; the two people can reply in the share thread."""
    return await services_for_request().circles.share_direct(email, kind, recipe_id, week_start, meal_id)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_shared_item(share_id: str) -> dict[str, Any]:
    """Read one circle message or share and its thread. Week shares include every meal slot and full snapshots of referenced recipes and ready foods."""
    return await services_for_request().circles.get_shared_item(share_id)


@mcp.tool(annotations=SHARE, structured_output=True)
async def send_circle_message(circle_id: str, body: str, attachment_kind: str | None = None,
                              attachment_id: str | None = None, mention_ids: list[str] | None = None,
                              expected_audience: list[str] | None = None) -> dict[str, Any]:
    """Post to an accepted private circle. Optionally attach one recipe or saved meal snapshot and mention accepted circle member IDs. The attachment is shared with the circle and opens a thread."""
    return await services_for_request().circles.send_message(circle_id, body, attachment_kind,
        attachment_id, mention_ids, expected_audience)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_circle_mention_candidates(circle_id: str) -> dict[str, Any]:
    """List accepted members who may be tagged in a circle message or share thread. Only available to accepted members."""
    return await services_for_request().circles.mention_candidates(circle_id)


@mcp.tool(annotations=SHARE, structured_output=True)
async def share_week_to_circle(circle_id: str, week_start: str,
                               expected_audience: list[str] | None = None) -> dict[str, Any]:
    """Explicitly publish one immutable whole-week meal plan snapshot to an accepted friend circle. Later plan edits are not published automatically."""
    return await services_for_request().circles.share_week(circle_id, week_start, expected_audience)


@mcp.tool(annotations=SHARE, structured_output=True)
async def share_recipe_to_circle(circle_id: str, recipe_id: str) -> dict[str, Any]:
    """Explicitly publish one recipe or ready food snapshot to an accepted friend circle."""
    return await services_for_request().circles.share_recipe(circle_id, recipe_id)


@mcp.tool(annotations=APPEND, structured_output=True)
async def comment_on_circle_share(share_id: str, body: str, target_type: str = "post", target_id: str | None = None,
                                  mention_ids: list[str] | None = None) -> dict[str, Any]:
    """Discuss a shared week, a specific planned meal, or a recipe in the share. Use target_type post, meal, or recipe with target_id for meal/recipe."""
    return await services_for_request().circles.comment(share_id, body, target_type, target_id, mention_ids)


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def delete_circle_comment(comment_id: str) -> dict[str, Any]:
    """Remove a comment you wrote or a comment on your post or circle. This also withdraws its notification."""
    return await services_for_request().circles.delete_comment(comment_id)


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_circle_recipe(share_id: str, recipe_id: str) -> dict[str, Any]:
    """Save one shared recipe or ready food as an independent copy in the active household; returns the existing copy on repeat."""
    return await services_for_request().circles.save_shared_recipe(share_id, recipe_id)


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def revoke_circle_share(share_id: str) -> dict[str, Any]:
    """Hide a circle share from all recipients. Only its creator may revoke it."""
    return await services_for_request().circles.revoke_share(share_id)


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
async def search_recipes(query: str = "", limit: int = 10, tag: str = "") -> dict[str, Any]:
    """Search saved recipes by title, description, or tag. Set tag for an exact tag filter."""
    items = await services_for_request().food.search_recipes(query=query, limit=limit, tag=tag)
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_recipe_tags() -> dict[str, Any]:
    """List existing tags and recipe counts for the active household; use these for tag suggestions."""
    items = await services_for_request().food.list_recipe_tags()
    return {"items": items, "count": len(items)}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_recipe_graph(query: str = "", filters: dict[str, list[str]] | None = None,
                           max_minutes: int | None = None) -> dict[str, Any]:
    """Explore search results with the same cuisine/goal/meal/diet/tag filters as browsing.
    Includes matching recipes and directly linked variations or serving partners; isMatch marks the search matches.
    No filters returns all active recipes. Related recipes can be outside the search filters.
    """
    return await services_for_request().food.get_recipe_graph(query, filters, max_minutes)


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_recipe_relationship(relationship: dict[str, Any]) -> dict[str, Any]:
    """Add or edit a recipe detail. Supply sourceRecipeId and type, plus id to edit.
    Types cuisine/goal/meal/diet/tag use label; variant_of/pairs_with use targetRecipeId.
    variant_of points from variation to base recipe. Categories are explicit household labels.
    """
    return await services_for_request().food.save_recipe_relationship(relationship)


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def delete_recipe_relationship(relationship_id: str) -> dict[str, Any]:
    """Remove a recipe connection by its id."""
    return await services_for_request().food.delete_recipe_relationship(relationship_id)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_recipe(recipe_id: str, variation: str | None = None) -> dict[str, Any]:
    """Get one recipe by its UUID. Optional variation selects one named nutrition view; unknown names fail without changing the recipe."""
    return await services_for_request().food.get_recipe(recipe_id, variation)


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Create or update a household recipe. Category lists: cuisines, eating_goals, meal_types, diets, tags.
    Use kind recipe or ready_food. Ready food has heating/serving instructions and no ingredient demand.
    Optional recipe variations use nutrition.profiles: [{name: custom label, serving: ingredient/preparation/serving changes}]. Nutrition is optional; basis is required only when nutrient guidance or numbers are included. Optional recipe nutrition uses {basis, profiles} with per-serving numeric amounts, portion and valueType. Omitted nutrition retains saved values; null clears it.
    Omitted typed categories retain saved values. Use totalMinutes for total cooking time.
    """
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


@mcp.tool(annotations=SHARE, structured_output=True)
async def create_meal_share(meal_id: str, expires_at: str | None = None) -> dict[str, Any]:
    """Publish a read-only snapshot of one saved meal and its referenced recipes to a revocable public link. Anyone with the link can view it; public shares have no comments."""
    share = await services_for_request().food.create_meal_share(meal_id, expires_at)
    return {**share, "url": f"{settings.app_base_url.rstrip('/')}/s/{share['token']}"}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_public_shares() -> dict[str, Any]:
    """List public recipe and saved-meal links created by this account, including links that can be copied again and revoked or expired link history. Older hash-only links cannot be recovered."""
    items = await services_for_request().food.list_public_shares()
    return {"items": [{**item, "url": f"{settings.app_base_url.rstrip('/')}/s/{item['token']}" if item.get("token") else None}
                      for item in items], "count": len(items)}


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def revoke_public_share(share_id: str) -> dict[str, Any]:
    """Revoke a public recipe or meal link created by this account. Further views fail immediately."""
    return await services_for_request().food.revoke_public_share(share_id)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def list_recipe_shares() -> dict[str, Any]:
    """List recipe link metadata created by the caller. For recoverable active links, use list_public_shares."""
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
    """Save an approved plan: weekStart (Monday), entries [{id?, date, slot: household slot ID, meal, servings?, notes?, components:[{id?, name, quantity?, unit?, source: ready|cook|task|external, action: cook|heat|serve, recipeId?, pantryItemId?, taskId?, notes?}]}], tasks [{id?, date?, title, notes?, recipeId?, servings?, mealIds?:[]}]. Historical entry nutrition is accepted for compatibility; create new variations on recipes. Existing entry nutrition schema: {basis: text, profiles: [{name, serving: plate instructions, macros: {protein, carbs, fat, fiber: unknown|low|moderate|high}, micronutrients: [{nutrient, source: food}]}]}. Optional profile portion (required with numbers), valueType: estimated|label, amounts: {calories: kcal number, protein/carbs/fat/fiber: gram numbers}; micronutrients may include amount and unit: g|mg|mcg. Numbers must be finite nonnegative with at most 3 decimals. Values are per stated portion, never daily targets; omitted data is unknown. Put actual additions in the recipe ingredients so shopping can account for them. Tasks need no slot or meal link. Supply stable UUIDs when linking new items. Cook components require recipeId; task components require taskId. Saving never changes stock."""
    return await services_for_request().planning.save_meal_plan(plan)


@mcp.tool(annotations=WRITE, structured_output=True)
async def configure_meal_slots(slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Save ordered household eating slots [{id, name, enabled}]. Read context first; keep stable IDs when renaming/reordering, disable instead of deleting existing IDs. Prep belongs in tasks. Keep at least one enabled slot."""
    return await services_for_request().household.configure_meal_slots(slots)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def search_meals(query: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Search active reusable meals by name, notes, or components in this household. Return items/total/offset/limit. Saved meals combine recipes and ready food independently of dates."""
    return await services_for_request().planning.meals.search(query, limit, offset)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_meal(meal_id: str) -> dict[str, Any]:
    """Read one reusable meal, including an archived meal referenced by history."""
    return await services_for_request().planning.meals.get(meal_id)


@mcp.tool(annotations=APPEND, structured_output=True)
async def save_meal(meal: dict[str, Any]) -> dict[str, Any]:
    """Save a reusable combination: {id? for editing, name, servings: default people/servings, notes?, components:[{id?,name,quantity?,unit?,source:ready|cook|external,action:cook|heat|serve,recipeId?,notes?}]}. Cook requires an active household recipe. No dates, task IDs, or pantry-lot IDs. Library edits never rewrite planned copies."""
    return await services_for_request().planning.meals.save(meal)


@mcp.tool(annotations=APPEND, structured_output=True)
async def save_combination(recipe_ids: list[str], servings: float, notes: str | None = None,
                           name: str | None = None) -> dict[str, Any]:
    """Save a reusable combination of 2–10 existing household recipes or ready foods. Each item uses the stated servings; no date or pantry stock is changed. Validate all selections before saving."""
    return await services_for_request().planning.meals.save_combination(recipe_ids, servings, notes, name)


@mcp.tool(annotations=ARCHIVE, structured_output=True)
async def archive_meal(meal_id: str) -> dict[str, Any]:
    """Archive a reusable meal from future choices. Existing planned meals and stock stay unchanged."""
    return await services_for_request().planning.meals.archive(meal_id)


@mcp.tool(annotations=APPEND, structured_output=True)
async def plan_saved_meal(week_start: str, meal_id: str, planned_date: str, slot: str, servings: float | None = None,
                          notes: str | None = None) -> dict[str, Any]:
    """Add a dated copy of a reusable meal to a week. Optionally override servings and notes for this occurrence. Scale component quantities; snapshot recipe ingredients and meal revision. Stock stays unchanged."""
    return await services_for_request().planning.plan_saved_meal(week_start, meal_id, planned_date, slot, servings, notes)


@mcp.tool(annotations=APPEND, structured_output=True)
async def plan_recipe(week_start: str, recipe_id: str, planned_date: str, slot: str, servings: float | None = None,
                      notes: str | None = None) -> dict[str, Any]:
    """Add a household recipe or ready food to a weekly meal slot with optional servings and notes. Save a dated component and recipe snapshot; do not alter the library recipe or pantry stock."""
    return await services_for_request().planning.plan_recipe(week_start, recipe_id, planned_date, slot, servings, notes)


@mcp.tool(annotations=APPEND, structured_output=True)
async def plan_combination(week_start: str, recipe_ids: list[str], planned_date: str, slot: str,
                           servings: float, notes: str | None = None) -> dict[str, Any]:
    """Combine 2–10 existing household recipes or ready foods into one dated meal. Each item gets the specified servings. Validate all IDs before writing; preserve the linked recipes for opening and shopping. No new library entry or pantry use."""
    return await services_for_request().planning.plan_combination(week_start, recipe_ids, planned_date, slot, servings, notes)


@mcp.tool(annotations=APPEND, structured_output=True)
async def save_planned_meal(week_start: str, item_id: str, name: str | None = None, servings: float | None = None) -> dict[str, Any]:
    """Save a planned meal as a new reusable combination. Keep component amounts, strip pantry-lot and task links, resolve recipe batches to cook components. Default servings use the planned servings or 1 if unknown; specify the correct basis when unknown."""
    return await services_for_request().planning.save_planned_meal(week_start, item_id, name, servings)


@mcp.tool(annotations=WRITE, structured_output=True)
async def update_plan_item(week_start: str, kind: str, item: dict[str, Any]) -> dict[str, Any]:
    """Add or patch one meal or task without replacing other items. kind: meal|task. Omit item.id to add; supply its saved ID to edit. Meals use date, slot, meal, components; tasks use title, optional date, notes, recipeId, servings, mealIds. Completed items are history."""
    return await services_for_request().planning.update_plan_item(week_start, kind, item)


@mcp.tool(annotations=WRITE, structured_output=True)
async def complete_plan_item(week_start: str, kind: str, item_id: str,
                             inputs: list[dict[str, Any]] | None = None,
                             outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Record a task done or a meal eaten. Inputs [{itemId, quantity}] are actual amounts USED in the pantry item's saved unit; outputs [{name, quantity, unit, storageLocation?}] create prepared stock. Ask for unknown actual amounts. Ordinary tasks can omit both. Atomic and safe to retry: each item completes once."""
    result = await services_for_request().planning.complete_item(week_start, kind, item_id, inputs, outputs)
    return {**result, "plan": with_weekly_nutrition(result["plan"])}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def preview_plan_shopping(week_start: str) -> dict[str, Any]:
    """Preview this week's remaining meal/task demand: scale recipe snapshots, count batches once, subtract exact stock once, and report unknown quantities/conversions. Does not save, reserve, buy, or consume food. Reconcile other-week commitments and English notes before saving the final shopping list."""
    return await services_for_request().planning.preview_shopping(week_start)


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_plan_shopping(week_start: str) -> dict[str, Any]:
    """Save reviewed shopping suggestions for a week, recalculating from current stock. Replace only pending generated items for this week; preserve manual items and purchase history. Review preview_plan_shopping warnings first; for NLP adjustments use save_shopping_list with an explicitly reconciled list."""
    return await services_for_request().planning.save_plan_shopping(week_start)


@mcp.tool(annotations=WRITE, structured_output=True)
async def receive_shopping_item(item_id: str, quantity: float, unit: str, storage_location: str = "pantry") -> dict[str, Any]:
    """Record an actual shopping item received: mark purchased and add pantry stock in its actual quantity/unit (e.g. 20 pieces, not one pack). Safe to retry, one receipt per shopping line. Never places an order."""
    return await services_for_request().shopping.receive_item(item_id, quantity, unit, storage_location)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_meal_plan(week_start: str | None = None) -> dict[str, Any]:
    """Return the meal plan for a week, or the latest plan when no week is supplied."""
    plan = await services_for_request().planning.get_meal_plan(week_start)
    return {"plan": plan, "nutritionSummary": weekly_nutrition(plan)}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_weekly_nutrition(week_start: str | None = None, variation: str | None = None) -> dict[str, Any]:
    """Totals of known numbers for one stated plate per variation per planned meal, with meal coverage for each nutrient. Optional variation selects one named view. Partial data is not a complete weekly total or household consumption."""
    return await services_for_request().planning.get_weekly_nutrition(week_start, variation)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_meal_plan_rules(revision_id: str | None = None) -> dict[str, Any]:
    """Read the current English planning rules, or an immutable revision by ID. Null means no rules saved."""
    return {"rules": await services_for_request().planning.get_rules(revision_id)}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def get_meal_plan_rule_history(limit: int = 20) -> dict[str, Any]:
    """Read saved English rule revisions, newest first, for the active household."""
    return {"items": await services_for_request().planning.get_rule_history(limit)}


@mcp.tool(annotations=WRITE, structured_output=True)
async def save_meal_plan_rules(text: str, expected_revision: int) -> dict[str, Any]:
    """Save a user-requested English rules document as a new revision. Read current rules first; pass its revision, or 0 if none. Blank text clears recurring rules while preserving history. A stale revision fails; reread and reconcile with the user."""
    return await services_for_request().planning.save_rules(text, expected_revision)


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
    """Load rules, current plan, two earlier saved weeks, pantry, recipe tags, week notes, feedback and preferences. Search saved recipes and their feedback summaries before drafting; no plan is generated or saved by this read."""
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


@mcp.tool(annotations=READ_ONLY, meta={"ui": {"resourceUri": RECIPE_LIBRARY_UI_URI}}, structured_output=True)
async def render_meal_library(query: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Open the shared recipe library with the Meals type filter selected."""
    return await render_recipe_library(query=query, limit=limit, item_type="meals", offset=offset)


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": RECIPE_LIBRARY_UI_URI}},
    structured_output=True,
)
async def render_recipe_library(query: str = "", limit: int = 50, tag: str = "", filters: dict[str, list[str]] | None = None,
                                max_minutes: int | None = None, item_type: str = "all", offset: int = 0) -> dict[str, Any]:
    """Search recipes and reusable meals together. Filter item_type by all, recipes, ready_food, or meals.
    Recipe filters match recipes inside meals. Open component recipes with get_recipe.
    """
    service = services_for_request().food
    selected = {**(filters or {})}
    if tag: selected["tag"] = [tag]
    data = await service.browse_recipe_library(query, selected, max_minutes, limit, offset, item_type)
    return {"kind": "recipe_library", **data, "exploreOpen": False, "recipes": data["items"], "tag": tag,
            "tags": [{"tag": item["label"], "recipe_count": item["count"]} for item in data["facets"]["tag"]],
            "household": await services_for_request().household.get_context()}


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def browse_recipe_library(query: str = "", filters: dict[str, list[str]] | None = None,
                                max_minutes: int | None = None, limit: int = 25, offset: int = 0, item_type: str = "recipes") -> dict[str, Any]:
    """Filter active household recipes and meals (item_type: all, recipes, ready_food, meals). Filter keys: cuisine, goal, meal, diet, tag. OR within a key, AND across keys.
    Categories are household-entered labels, not verified nutrition. Use get_recipe_graph for variations and serving pairings.
    """
    return await services_for_request().food.browse_recipe_library(query, filters, max_minutes, limit, offset, item_type)


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": RECIPE_LIBRARY_UI_URI}},
    structured_output=True,
)
async def render_recipe_graph(query: str = "", filters: dict[str, list[str]] | None = None,
                              max_minutes: int | None = None) -> dict[str, Any]:
    """Render recipe search with its Explore results panel open. Categories and recipe links remain editable."""
    return {"kind": "recipe_graph", "graph": await services_for_request().food.get_recipe_graph(query, filters, max_minutes)}


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
    plan = await services_for_request().planning.get_plan_view(week_start)
    return {"kind": "meal_plan", "plan": plan, "household": await services_for_request().household.get_context()}


@mcp.tool(
    annotations=READ_ONLY,
    meta={"ui": {"resourceUri": SHOPPING_UI_URI}},
    structured_output=True,
)
async def render_shopping_list(list_id: str | None = None) -> dict[str, Any]:
    """Render the final grouped shopping checklist. Call get_shopping_list first when reasoning over it."""
    value = await services_for_request().shopping.get(list_id)
    return {"kind": "shopping_list", "shoppingList": value}


def _ui_resource() -> str:
    """Keep embedded controls self-contained in hosts that disallow asset requests."""
    html = mcp_app_html()
    css = (STATIC_DIR / "choices.css").read_text(encoding="utf-8")
    script = (STATIC_DIR / "choices.js").read_text(encoding="utf-8")
    return html.replace(
        '<link rel="stylesheet" href="/static/choices.css?v=1" />', f"<style>{css}</style>",
    ).replace(
        '<script src="/static/choices.js?v=1" defer></script>', f"<script>{script}</script>",
    )


@mcp.resource(
    MEAL_PLAN_UI_URI,
    name="meal-plan-ui",
    title="Meal plan calendar",
    description="A compact weekly meal-plan calendar.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def meal_plan_resource() -> str:
    return _ui_resource()


@mcp.resource(
    SHOPPING_UI_URI,
    name="shopping-list-ui",
    title="Shopping checklist",
    description="A shopping checklist grouped by store.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def shopping_list_resource() -> str:
    return _ui_resource()


@mcp.resource(
    HOUSEHOLD_UI_URI,
    name="household-dashboard-ui",
    title="Household meal-prep dashboard",
    description="A chat-configured card dashboard of household rules and saved meal-prep data.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def household_snapshot_resource() -> str:
    return _ui_resource()


@mcp.resource(
    ONBOARDING_UI_URI,
    name="onboarding-ui",
    title="Household food planning setup",
    description="Set up the household food week across meals, prep, pantry, and shopping.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def onboarding_resource() -> str:
    return _ui_resource()


@mcp.resource(
    RECIPE_LIBRARY_UI_URI,
    name="recipe-library-ui",
    title="Recipe library",
    description="A visual, searchable library of household recipes and reusable meals.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def recipe_library_resource() -> str:
    return _ui_resource()


@mcp.resource(
    FEEDBACK_UI_URI,
    name="feedback-ui",
    title="Meal and week feedback",
    description="Saved feedback about meals, recipes, and weekly planning.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True}},
)
def feedback_resource() -> str:
    return _ui_resource()


@mcp.resource(
    PANTRY_EVIDENCE_UI_URI,
    name="pantry-evidence-ui",
    title="Pantry photo evidence",
    description="Review compact saved pantry photos and the items observed in each.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True, "csp": {"resourceDomains": [settings.supabase_url.rstrip('/')] if settings.supabase_url else []}}},
)
def pantry_evidence_resource() -> str:
    return _ui_resource()


mcp_app = mcp.streamable_http_app()
