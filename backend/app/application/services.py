from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import re
from typing import Any, Awaitable, Callable, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from .errors import ApplicationError, RepositoryError, StorageNotInstalledError
from .pantry_photos import compact_photo, download_chatgpt_photo, normalize_observations
from .pantry_categories import PANTRY_CATEGORIES, infer_pantry_category
from .pantry_freshness import pantry_freshness
from .planning_model import meal_slots, validate_slots, component, identifier, text, positive, iso_date
from .meal_library import MealLibrary, copy_components, components_from_plan
from .circles import CircleService


DASHBOARD_CARD_IDS = (
    "food-rules",
    "planning-defaults",
    "stores",
    "schedule",
    "meal-plan",
    "shopping-list",
    "pantry",
    "recipes",
    "feedback",
    "memories",
)


def _dashboard_layout(preferences: dict[str, Any]) -> dict[str, list[str]]:
    saved = preferences.get("dashboard") or {}
    requested_order = saved.get("cardOrder") or saved.get("card_order") or []
    order = list(dict.fromkeys(card_id for card_id in requested_order if card_id in DASHBOARD_CARD_IDS))
    order.extend(card_id for card_id in DASHBOARD_CARD_IDS if card_id not in order)
    requested_hidden = saved.get("hiddenCards") or saved.get("hidden_cards") or []
    hidden = list(dict.fromkeys(card_id for card_id in requested_hidden if card_id in DASHBOARD_CARD_IDS))
    return {"cardOrder": order, "hiddenCards": hidden}


class MealPrepRepository(Protocol):
    async def circle_list(self) -> list[dict[str, Any]]: ...
    async def circle_create(self, name: str) -> dict[str, Any]: ...
    async def circle_invite(self, circle_id: str, email: str) -> dict[str, Any]: ...
    async def circle_respond(self, circle_id: str, accept: bool) -> dict[str, Any]: ...
    async def circle_remove_friend(self, circle_id: str, user_id: str) -> dict[str, Any]: ...
    async def circle_leave(self, circle_id: str) -> dict[str, Any]: ...
    async def circle_feed(self, limit: int, offset: int, kind: str | None, circle_id: str | None) -> list[dict[str, Any]]: ...
    async def circle_get_post(self, share_id: str) -> dict[str, Any]: ...
    async def circle_share_week(self, circle_id: str, week_start: str) -> dict[str, Any]: ...
    async def circle_share_recipe(self, circle_id: str, recipe_id: str) -> dict[str, Any]: ...
    async def circle_comment(self, share_id: str, body: str, target_type: str, target_id: str | None) -> dict[str, Any]: ...
    async def circle_delete_comment(self, comment_id: str) -> dict[str, Any]: ...
    async def circle_save_recipe(self, share_id: str, recipe_id: str) -> dict[str, Any]: ...
    async def circle_revoke_post(self, share_id: str) -> dict[str, Any]: ...
    async def search_meals(self, query: str, limit: int, offset: int) -> dict: ...
    async def get_meal(self, meal_id: str) -> dict | None: ...
    async def save_meal(self, meal: dict) -> dict: ...
    async def archive_meal(self, meal_id: str) -> dict: ...
    async def get_household_context(self, *, create_if_missing: bool = True) -> dict[str, Any]: ...
    async def list_households(self) -> dict[str, Any]: ...
    async def switch_household(self, household_id: str) -> dict[str, Any]: ...
    async def create_household(self, name: str) -> dict[str, Any]: ...
    async def update_household_preferences(self, patch: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def search_recipes(self, query: str = "", limit: int = 10, tag: str = "") -> list[dict[str, Any]]: ...
    async def list_recipe_tags(self) -> list[dict[str, Any]]: ...
    async def get_recipe_graph_data(self) -> dict[str, Any]: ...
    async def save_recipe_relationship(self, relationship: dict[str, Any]) -> dict[str, Any]: ...
    async def delete_recipe_relationship(self, relationship_id: str) -> bool: ...
    async def get_recipe(self, recipe_id: str) -> dict[str, Any] | None: ...
    async def save_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]: ...
    async def archive_recipe(self, recipe_id: str) -> dict[str, Any]: ...
    async def create_recipe_share(self, recipe_id: str, expires_at: str | None = None) -> dict[str, Any]: ...
    async def create_meal_share(self, meal_id: str, expires_at: str | None = None) -> dict[str, Any]: ...
    async def list_public_shares(self) -> list[dict[str, Any]]: ...
    async def revoke_public_share(self, share_id: str) -> bool: ...
    async def list_recipe_shares(self) -> list[dict[str, Any]]: ...
    async def revoke_recipe_share(self, share_id: str) -> bool: ...
    async def copy_shared_recipe(self, token: str) -> str: ...
    async def get_pantry(self) -> list[dict[str, Any]]: ...
    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]: ...
    async def record_pantry_use(self, item_id: str, quantity: float, recipe_id: str | None = None, meal_title: str | None = None) -> dict[str, Any]: ...
    async def save_pantry_photo(self, *, image: bytes, width: int, height: int, file_id: str, note: str, observations: list[dict[str, Any]], apply_to_pantry: bool) -> dict[str, Any]: ...
    async def get_pantry_photos(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]: ...
    async def apply_pantry_photo(self, evidence_id: str, observations: list[dict[str, Any]] | None = None) -> dict[str, Any]: ...
    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]: ...
    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None: ...
    async def get_recent_meal_plans(self, before_week: str, limit: int = 2) -> list[dict[str, Any]]: ...
    async def complete_plan_item(self, week_start: str, kind: str, item_id: str, inputs: list[dict], outputs: list[dict]) -> dict: ...
    async def receive_shopping_item(self, item_id: str, quantity: float, unit: str, storage_location: str) -> dict: ...
    async def get_meal_plan_rules(self, revision_id: str | None = None) -> dict[str, Any] | None: ...
    async def get_meal_plan_rule_history(self, limit: int = 20) -> list[dict[str, Any]]: ...
    async def save_meal_plan_rules(self, text: str, expected_revision: int) -> dict[str, Any]: ...
    async def save_shopping_list(self, shopping_list: dict[str, Any]) -> dict[str, Any]: ...
    async def get_shopping_list(self, list_id: str | None = None) -> dict[str, Any] | None: ...
    async def add_shopping_item(self, item: dict[str, Any], list_id: str | None = None) -> dict[str, Any]: ...
    async def mark_item_purchased(
        self,
        item_id: str,
        purchased: bool = True,
        purchased_quantity: float | None = None,
    ) -> dict[str, Any]: ...
    async def get_weekly_schedule(self, week_start: str | None = None) -> dict[str, Any] | None: ...
    async def save_weekly_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]: ...
    async def get_feedback(
        self,
        recipe_id: str | None = None,
        week_start: str | None = None,
        tags: list[str] | None = None,
        feedback_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...
    async def save_feedback(self, feedback: dict[str, Any]) -> dict[str, Any]: ...
    async def get_household_memory(
        self,
        include_inactive: bool = False,
        status: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...
    async def save_household_memory(self, memory: dict[str, Any]) -> dict[str, Any]: ...
    async def review_household_memory(
        self,
        memory_id: str,
        action: str,
        content: str | None = None,
    ) -> dict[str, Any]: ...


class HouseholdService:
    def __init__(self, repository: MealPrepRepository):
        self.repository = repository

    async def get_context(self) -> dict[str, Any]:
        household = await self.repository.get_household_context()
        return {**household, "mealSlots": meal_slots(household)}

    async def configure_meal_slots(self, slots: list[dict]) -> dict:
        household = await self.repository.get_household_context()
        cleaned = validate_slots(slots, meal_slots(household))
        preferences = household.get("planningPreferences") or {}
        updated = await self.repository.update_household_preferences(
            {"planningPreferences": {**preferences, "mealSlots": cleaned}}, context=household)
        return {**updated, "mealSlots": cleaned}

    async def list_households(self) -> dict[str, Any]:
        return await self.repository.list_households()

    async def switch_household(self, household_id: str) -> dict[str, Any]:
        return await self.repository.switch_household(household_id)

    async def create_household(self, name: str) -> dict[str, Any]:
        return await self.repository.create_household(name)

    async def update_preferences(
        self,
        *,
        household_size: int | None = None,
        dietary_restrictions: list[str] | None = None,
        store_priority: list[dict[str, Any]] | None = None,
        planning_preferences: dict[str, Any] | None = None,
        complete_onboarding: bool = False,
    ) -> dict[str, Any]:
        if planning_preferences is not None:
            household = await self.repository.get_household_context()
            if "mealSlots" in planning_preferences:
                planning_preferences = {**planning_preferences, "mealSlots": validate_slots(
                    planning_preferences["mealSlots"], meal_slots(household))}
            planning_preferences = {**(household.get("planningPreferences") or {}), **planning_preferences}
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
                raise ApplicationError(f"Cannot complete onboarding; missing: {', '.join(missing)}")

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
        return await self.repository.update_household_preferences(patch)

    async def get_dashboard_layout(self) -> dict[str, Any]:
        household = await self.repository.get_household_context()
        preferences = household.get("planningPreferences") or household.get("planning_preferences") or {}
        return {
            **_dashboard_layout(preferences),
            "availableCards": list(DASHBOARD_CARD_IDS),
        }

    async def configure_dashboard(
        self,
        *,
        card_order: list[str] | None = None,
        hidden_cards: list[str] | None = None,
        reset_to_default: bool = False,
    ) -> dict[str, Any]:
        household = await self.repository.get_household_context()
        preferences = household.get("planningPreferences") or household.get("planning_preferences") or {}
        current = _dashboard_layout(preferences)

        if reset_to_default:
            order = list(DASHBOARD_CARD_IDS)
            hidden: list[str] = []
        else:
            requested_order = card_order or []
            requested_hidden = hidden_cards if hidden_cards is not None else current["hiddenCards"]
            invalid = sorted(
                {
                    card_id
                    for card_id in [*requested_order, *requested_hidden]
                    if card_id not in DASHBOARD_CARD_IDS
                }
            )
            if invalid:
                raise ApplicationError(f"Unknown dashboard card IDs: {', '.join(invalid)}")
            if len(requested_order) != len(set(requested_order)):
                raise ApplicationError("card_order cannot contain duplicate card IDs")
            if len(requested_hidden) != len(set(requested_hidden)):
                raise ApplicationError("hidden_cards cannot contain duplicate card IDs")
            order = requested_order + [
                card_id for card_id in current["cardOrder"] if card_id not in requested_order
            ] if card_order is not None else current["cardOrder"]
            hidden = requested_hidden

        layout = {"cardOrder": order, "hiddenCards": hidden}
        updated = await self.repository.update_household_preferences(
            {"planningPreferences": {**preferences, "dashboard": layout}}, context=household
        )
        return {
            **layout,
            "availableCards": list(DASHBOARD_CARD_IDS),
            "household": updated,
        }

    async def snapshot(
        self, *, sections: list[str] | None = None, week_start: str | None = None,
    ) -> dict[str, Any]:
        async def section(loader: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
            try:
                value = await loader()
            except RepositoryError:
                return {"status": "unavailable", "value": None}
            empty = value is None or value == [] or value == {}
            return {"status": "empty" if empty else "ready", "value": value}

        loaders = {
            "pantry": RecipePantryService(self.repository).get_pantry,
            "recipes": lambda: self.repository.search_recipes(query="", limit=25),
            "meals": lambda: MealLibrary(self.repository).search(),
            "schedule": lambda: self.repository.get_weekly_schedule(week_start),
            "feedback": lambda: self.repository.get_feedback(limit=25),
            "memories": self.repository.get_household_memory,
            "mealPlan": lambda: self.repository.get_meal_plan(week_start),
            "mealPlanRules": self.repository.get_meal_plan_rules,
            "shoppingList": self.repository.get_shopping_list,
        }
        if sections is not None:
            unknown = set(sections) - loaders.keys()
            if unknown:
                raise ApplicationError(f"Unknown snapshot sections: {', '.join(sorted(unknown))}")
            loaders = {name: loaders[name] for name in dict.fromkeys(sections)}
        household = await self.get_context()
        values = await asyncio.gather(*(section(loader) for loader in loaders.values()))
        return {
            "household": household,
            "sections": dict(zip(loaders, values)),
        }


class RecipePantryService:
    def __init__(self, repository: MealPrepRepository):
        self.repository = repository

    async def search_recipes(self, query: str = "", limit: int = 10, tag: str = "") -> list[dict[str, Any]]:
        return await self.repository.search_recipes(query=query, limit=limit, tag=tag.strip().casefold())

    async def list_recipe_tags(self) -> list[dict[str, Any]]:
        return await self.repository.list_recipe_tags()

    async def browse_recipe_library(self, query: str = "", filters: dict | None = None,
                                   max_minutes: int | None = None, limit: int = 25, offset: int = 0,
                                   item_type: str = "recipes") -> dict:
        from .recipe_browsing import browse
        if item_type not in {"all", "recipes", "ready_food", "meals"}:
            raise ApplicationError("Library type must be all, recipes, ready_food, or meals")
        graph = await self.repository.get_recipe_graph_data()
        recipe_graph = {**graph, "recipes": [
            r for r in graph["recipes"] if item_type not in {"recipes", "ready_food"}
            or (r.get("kind", "recipe") == "ready_food") == (item_type == "ready_food")]}
        recipes = browse(recipe_graph, query, filters, max_minutes, limit, offset)
        if item_type in {"recipes", "ready_food"}:
            return {**recipes, "itemType": item_type}
        # Meal search remains household scoped and covers every page, including
        # names, notes, and ready foods that have no recipe.
        meals = []
        while True:
            page = await self.repository.search_meals(query, 100, len(meals))
            meals.extend(page["items"])
            if len(meals) >= page["total"]:
                break
        # Recipe facets also count matching meals through their linked dishes.
        # Otherwise a search for a meal's name would disable all its recipe filters.
        from .recipe_graph import CATEGORY_FIELDS
        by_id = {r["id"]: r for r in graph["recipes"]}
        facets = {}
        for kind, options in recipes["facets"].items():
            other_filters = {key: values for key, values in recipes["filters"].items() if key != kind}
            eligible = set(browse(graph, "", other_filters, max_minutes)["matchingRecipeIds"])
            facets[kind] = [{**option, "count": (option["count"] if item_type == "all" else 0) + sum(
                any(row.get("recipeId") in eligible and option["label"] in
                    (by_id[row["recipeId"]].get(CATEGORY_FIELDS[kind]) or []) for row in meal["components"])
                for meal in meals)} for option in options]
        if recipes["filters"] or max_minutes is not None:
            eligible = set(browse(graph, "", filters, max_minutes)["matchingRecipeIds"])
            meals = [meal for meal in meals if any(row.get("recipeId") in eligible for row in meal["components"])]
        recipe_ids = set(recipes["matchingRecipeIds"])
        items = [{**r, "itemType": "ready_food" if r.get("kind") == "ready_food" else "recipes"} for r in graph["recipes"] if r["id"] in recipe_ids] if item_type == "all" else []
        # Keep variation information on recipe cards in the mixed result set.
        variations = {}
        for edge in graph["relationships"]:
            if edge["type"] == "variant_of":
                target = edge["targetRecipeId"]
                variations[target] = variations.get(target, 0) + 1
        items = [{**r, "variationCount": variations.get(r["id"], 0)} for r in items]
        items.extend({**meal, "itemType": "meals"} for meal in meals)
        # Alphabetical ordering makes paging stable across the two primitives.
        items.sort(key=lambda row: ((row.get("title") or row["name"]).casefold(), row["id"]))
        total_meals = (await self.repository.search_meals("", 1, 0))["total"]
        return {**recipes, "items": items[offset:offset + limit], "count": len(items),
                "totalCount": total_meals + (recipes["totalCount"] if item_type == "all" else 0),
                "matchingRecipeIds": recipes["matchingRecipeIds"] if item_type == "all" else [],
                "itemType": item_type, "facets": facets, "hasMore": offset + limit < len(items)}

    async def get_recipe_graph(self, query: str = "", filters: dict | None = None,
                               max_minutes: int | None = None) -> dict[str, Any]:
        from .recipe_browsing import browse
        from .recipe_graph import build_result_graph
        data = await self.repository.get_recipe_graph_data()
        results = browse(data, query, filters, max_minutes)
        return {**build_result_graph(data, results["matchingRecipeIds"]),
                "scope": {"query": results["query"], "filters": results["filters"], "maxMinutes": max_minutes}}

    async def save_recipe_relationship(self, relationship: dict[str, Any]) -> dict[str, Any]:
        from .recipe_graph import validate_relationship
        clean = validate_relationship(relationship, await self.get_recipe_graph())
        return await self.repository.save_recipe_relationship(clean)

    async def delete_recipe_relationship(self, relationship_id: str) -> dict[str, Any]:
        graph = await self.get_recipe_graph()
        if not any(edge["id"] == relationship_id for edge in graph["edges"]):
            raise ApplicationError("Relationship was not found")
        if not await self.repository.delete_recipe_relationship(relationship_id):
            raise ApplicationError("Relationship was not found")
        return {"id": relationship_id, "deleted": True}

    async def get_recipe(self, recipe_id: str) -> dict[str, Any]:
        recipe = await self.repository.get_recipe(recipe_id)
        if not recipe:
            raise ApplicationError("Recipe was not found")
        try:
            feedback = await self.repository.get_feedback(recipe_id=recipe_id, limit=25)
        except StorageNotInstalledError as exc:
            if exc.feature != "feedback":
                raise
            return {**recipe, "feedback": [], "feedbackUnavailable": True}
        return {
            **recipe,
            "feedback": feedback,
            "feedbackUnavailable": False,
        }

    async def save_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        if not str(recipe.get("title", "")).strip():
            raise ApplicationError("recipe.title is required")
        existing = await self.repository.get_recipe(recipe["id"]) if recipe.get("id") and "kind" not in recipe else None
        kind = recipe.get("kind", (existing or {}).get("kind", "recipe"))
        if not isinstance(kind, str) or kind not in {"recipe", "ready_food"}:
            raise ApplicationError("Recipe kind must be recipe or ready_food")
        if kind == "ready_food" and recipe.get("ingredients"):
            raise ApplicationError("Ready food has no ingredient demand; save its preparation notes as instructions")
        values = recipe.get("tags", [])
        if not isinstance(values, list) or len(values) > 12:
            raise ApplicationError("recipe.tags must be a list of at most 12 tags")
        tags = []
        for value in values:
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 48:
                raise ApplicationError("recipe tags must be nonempty text of at most 48 characters")
            tag = " ".join(value.split()).casefold()
            if tag not in tags:
                tags.append(tag)
        from .recipe_browsing import normalize_categories
        from .recipe_graph import CATEGORY_FIELDS
        clean = {**recipe, "tags": tags, "kind": kind}
        for field in CATEGORY_FIELDS.values():
            if field != "tags" and field in recipe:
                clean[field] = normalize_categories(recipe[field], field)
        return await self.repository.save_recipe(clean)

    async def archive_recipe(self, recipe_id: str) -> dict[str, Any]:
        return await self.repository.archive_recipe(recipe_id)

    async def create_recipe_share(self, recipe_id: str, expires_at: str | None = None) -> dict[str, Any]:
        if not await self.repository.get_recipe(recipe_id):
            raise ApplicationError("Recipe was not found")
        if expires_at:
            try:
                parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed <= datetime.now(UTC):
                    raise ValueError
            except ValueError as exc:
                raise ApplicationError("expires_at must be a future ISO 8601 timestamp") from exc
        return await self.repository.create_recipe_share(recipe_id, expires_at)

    async def list_recipe_shares(self) -> list[dict[str, Any]]:
        return await self.repository.list_recipe_shares()

    async def create_meal_share(self, meal_id: str, expires_at: str | None = None) -> dict[str, Any]:
        if not await self.repository.get_meal(meal_id):
            raise ApplicationError("Meal was not found")
        if expires_at:
            try:
                parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed <= datetime.now(UTC):
                    raise ValueError
            except ValueError as exc:
                raise ApplicationError("expires_at must be a future ISO 8601 timestamp") from exc
        return await self.repository.create_meal_share(meal_id, expires_at)

    async def list_public_shares(self) -> list[dict[str, Any]]:
        return await self.repository.list_public_shares()

    async def revoke_public_share(self, share_id: str) -> dict[str, Any]:
        if not await self.repository.revoke_public_share(share_id):
            raise ApplicationError("Share was not found")
        return {"id": share_id, "revoked": True}

    async def revoke_recipe_share(self, share_id: str) -> dict[str, Any]:
        if not await self.repository.revoke_recipe_share(share_id):
            raise ApplicationError("Share was not found")
        return {"id": share_id, "revoked": True}

    async def copy_shared_recipe(self, token: str) -> dict[str, Any]:
        return {"recipeId": await self.repository.copy_shared_recipe(token)}

    async def get_pantry(self) -> list[dict[str, Any]]:
        return [{**item, "freshness": pantry_freshness(item)} for item in await self.repository.get_pantry()]

    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]:
        # Partial edits retain dates, provenance and the tracked stock baseline.
        existing = None
        if item.get("id"):
            existing = next((row for row in await self.repository.get_pantry() if row.get("id") == item["id"]), None)
        if item.get("id") and existing is None:
            raise ApplicationError("Pantry item was not found")
        merged = {**(existing or {}), **item}
        defaults = {"storageLocation": "pantry", "quantityConfidence": "estimated"}
        for camel, snake in (("storageLocation", "storage_location"), ("quantityConfidence", "quantity_confidence"),
                            ("useByDate", "use_by_date"), ("acquiredAt", "acquired_at"), ("freshnessBasis", "freshness_basis")):
            if camel not in item:
                previous = (existing or {}).get(camel, (existing or {}).get(snake, defaults.get(camel)))
                merged[camel] = item.get(snake, previous)
        item = merged
        if not str(item.get("name", "")).strip():
            raise ApplicationError("item.name is required")
        if item.get("quantity") is not None:
            from decimal import Decimal, InvalidOperation
            try:
                amount = Decimal(str(item["quantity"]))
            except (InvalidOperation, ValueError):
                raise ApplicationError("quantity must be a nonnegative number") from None
            if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -3:
                raise ApplicationError("quantity must be nonnegative with at most 3 decimal places")
            item["quantity"] = float(amount)
            if existing and existing.get("quantity") == 0 and amount > 0:
                item["reference_quantity"] = float(amount)
        for key in ("acquiredAt", "useByDate"):
            if item.get(key):
                try:
                    date.fromisoformat(item[key])
                except (ValueError, TypeError):
                    raise ApplicationError(f"{key} must be a valid date") from None
        if item.get("acquiredAt") and date.fromisoformat(item["acquiredAt"]) > datetime.now(ZoneInfo("America/Los_Angeles")).date():
            raise ApplicationError("Purchase date cannot be in the future")
        category = item.get("category")
        if category is not None and category not in PANTRY_CATEGORIES:
            raise ApplicationError("Invalid pantry category")
        if category is None:
            item = {**item, "category": (existing or {}).get("category") or infer_pantry_category(
                item["name"], item.get("storageLocation", item.get("storage_location", ""))
            )}
        return await self.repository.update_pantry_item(item)

    async def record_pantry_use(
        self, item_id: str, quantity: float, recipe_id: str | None = None,
        meal_title: str | None = None,
    ) -> dict[str, Any]:
        from decimal import Decimal, InvalidOperation

        if not item_id:
            raise ApplicationError("item_id is required")
        try:
            amount = Decimal(str(quantity))
        except (InvalidOperation, ValueError):
            raise ApplicationError("quantity must be a positive number") from None
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -3:
            raise ApplicationError("quantity must be positive with at most 3 decimal places")
        if meal_title is not None and len(meal_title.strip()) > 180:
            raise ApplicationError("meal_title must be 180 characters or fewer")
        try:
            return await self.repository.record_pantry_use(
                item_id, float(amount), recipe_id or None, meal_title.strip() if meal_title else None,
            )
        except RepositoryError as exc:
            if str(exc) in {
                "Pantry item was not found", "Set a remaining quantity before recording use",
                "Amount used exceeds the remaining quantity", "Recipe was not found",
                "Meal title is too long", "Amount used must be positive with at most 3 decimal places",
            }:
                raise ApplicationError(str(exc)) from exc
            raise

    async def save_pantry_photo(
        self, file: dict[str, str], observed_items: list[dict[str, Any]],
        storage_location: str = "fridge", note: str = "", apply_to_pantry: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(storage_location, str) or not 1 <= len(storage_location.strip()) <= 80:
            raise ApplicationError("storage_location is required")
        if not isinstance(note, str) or len(note) > 1000:
            raise ApplicationError("note must be at most 1000 characters")
        observations = normalize_observations(observed_items, storage_location.strip())
        image, width, height = compact_photo(await download_chatgpt_photo(file))
        return await self.repository.save_pantry_photo(
            image=image, width=width, height=height, file_id=file["file_id"],
            note=note, observations=observations, apply_to_pantry=apply_to_pantry,
        )

    async def get_pantry_photos(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        return await self.repository.get_pantry_photos(limit, offset)

    async def apply_pantry_photo(self, evidence_id: str, observed_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if observed_items is not None:
            observed_items = normalize_observations(observed_items, "fridge")
        return await self.repository.apply_pantry_photo(evidence_id, observed_items)


class PlanningService:
    def __init__(self, repository: MealPrepRepository):
        self.repository = repository
        self.meals = MealLibrary(repository)

    async def plan_saved_meal(self, week_start: str, meal_id: str, planned_date: str, slot: str, servings=None) -> dict:
        self._week(week_start)
        meal = await self.meals.get(meal_id)
        if meal.get("archivedAt"):
            raise ApplicationError("Archived meals cannot be added to a plan")
        target = positive(servings if servings is not None else meal["servings"], "Servings")
        components = copy_components(meal["components"], Decimal(str(target)) / Decimal(str(meal["servings"])))
        return await self.update_plan_item(week_start, "meal", {"date": planned_date, "slot": slot,
            "meal": meal["name"], "servings": target, "notes": meal["notes"], "components": components,
            "sourceMeal": {"id": meal["id"], "name": meal["name"], "revision": meal["revision"]}})

    async def save_planned_meal(self, week_start: str, item_id: str, name=None, servings=None) -> dict:
        self._week(week_start)
        plan = await self.repository.get_meal_plan(week_start) or {}
        entry = next((item for item in plan.get("entries", []) if item["id"] == item_id), None)
        if not entry:
            raise ApplicationError("Planned meal was not found")
        return await self.meals.save({"name": name if name is not None else entry["meal"],
            "servings": servings if servings is not None else entry.get("servings") or 1,
            "notes": entry["notes"], "components": components_from_plan(entry, plan.get("tasks", []))})

    async def get_context(self, week_start: str | None = None) -> dict[str, Any]:
        if week_start:
            self._week(week_start)
        household = await HouseholdService(self.repository).get_context()
        plan = await self.repository.get_meal_plan(week_start)
        before_week = week_start or (plan or {}).get("weekStart")
        if not before_week:
            today = date.today()
            before_week = (today - timedelta(days=today.weekday())).isoformat()
        loaders = {
            "schedule": self.repository.get_weekly_schedule(week_start),
            "feedback": self.repository.get_feedback(limit=25),
            "memories": self.repository.get_household_memory(),
            "mealPlanRules": self.repository.get_meal_plan_rules(),
            "recentPlans": self.repository.get_recent_meal_plans(before_week, limit=2),
            "pantry": RecipePantryService(self.repository).get_pantry(),
            "recipeTags": self.repository.list_recipe_tags(),
            "savedMeals": self.meals.search(),
        }
        values = await asyncio.gather(*loaders.values())
        return {"household": household, "mealPlan": plan, **dict(zip(loaders, values)),
                "requestedWeekStart": week_start}

    @staticmethod
    def _week(value: str) -> date:
        try:
            week = date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ApplicationError("weekStart must be an ISO date (YYYY-MM-DD)") from exc
        if week.isoformat() != value or week.weekday() != 0:
            raise ApplicationError("weekStart must be a Monday in YYYY-MM-DD format")
        return week

    async def get_rules(self, revision_id: str | None = None) -> dict[str, Any] | None:
        if revision_id is not None:
            try:
                UUID(revision_id)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ApplicationError("Invalid meal plan rule revision ID") from exc
        rules = await self.repository.get_meal_plan_rules(revision_id)
        if revision_id and rules is None:
            raise ApplicationError("Meal plan rule revision was not found")
        return rules

    async def get_rule_history(self, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ApplicationError("limit must be between 1 and 100")
        return await self.repository.get_meal_plan_rule_history(limit)

    async def save_rules(self, text: str, expected_revision: int) -> dict[str, Any]:
        if not isinstance(text, str) or len(text) > 10000:
            raise ApplicationError("Rules must be English text of at most 10000 characters")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ApplicationError("expectedRevision must be a nonnegative integer")
        return await self.repository.save_meal_plan_rules(text.strip(), expected_revision)

    async def get_schedule(self, week_start: str | None = None) -> dict[str, Any] | None:
        return await self.repository.get_weekly_schedule(week_start)

    async def save_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        if not schedule.get("weekStart") or len(schedule.get("days", [])) != 7:
            raise ApplicationError("schedule.weekStart and seven schedule.days are required")
        self._week(schedule["weekStart"])
        notes = schedule.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 3000:
            raise ApplicationError("Week notes must be text of at most 3000 characters")
        return await self.repository.save_weekly_schedule(schedule)

    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None:
        return await self.repository.get_meal_plan(week_start)

    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        if not plan.get("weekStart") or not isinstance(plan.get("entries"), list):
            raise ApplicationError("plan.weekStart and plan.entries are required")
        week = self._week(plan["weekStart"])
        if len(plan["entries"]) > 150 or not isinstance(plan.get("tasks", []), list) or len(plan.get("tasks", [])) > 150:
            raise ApplicationError("A plan may contain at most 150 meals and 150 tasks")
        existing = await self.repository.get_meal_plan(plan["weekStart"]) or {}
        if plan.get("id") and existing.get("id") != plan["id"]:
            raise ApplicationError("Plan ID does not belong to this week")
        slots = {slot["id"]: slot for slot in meal_slots(await self.repository.get_household_context())}
        previous = {item["id"]: item for item in [*existing.get("entries", []), *existing.get("tasks", [])]}
        previous_recipes = {**previous, **{row["id"]: row for meal in existing.get("entries", []) for row in meal.get("components", [])}}
        ids, component_ids = set(), set()
        recipes = {}
        pantry = {item["id"]: item for item in await self.repository.get_pantry()}

        async def recipe_snapshot(item):
            recipe_id = item.get("recipeId")
            if not recipe_id:
                return
            old = previous_recipes.get(item["id"], {})
            if old.get("recipeId") == recipe_id and old.get("recipeSnapshot"):
                item["recipeSnapshot"] = old["recipeSnapshot"]
                return
            if recipe_id not in recipes:
                recipes[recipe_id] = await self.repository.get_recipe(recipe_id)
            recipe = recipes[recipe_id]
            if not recipe or recipe.get("archived_at"):
                raise ApplicationError("Recipe was not found in this household")
            item["recipeSnapshot"] = {key: recipe.get(key) for key in ("title", "servings", "ingredients", "kind")}

        def identity(item):
            item_id = identifier(item.get("id"))
            if item_id in ids:
                raise ApplicationError("Plan item IDs must be unique")
            ids.add(item_id)
            return item_id

        tasks = []
        for value in plan.get("tasks", existing.get("tasks", [])):
            if not isinstance(value, dict):
                raise ApplicationError("Every task must be an object")
            task_id = identity(value)
            old = previous.get(task_id, {})
            linked = value.get("mealIds", [])
            if not isinstance(linked, list) or not all(isinstance(link, str) for link in linked) or len(linked) != len(set(linked)):
                raise ApplicationError("Task mealIds must be a list of unique meal IDs")
            if value.get("recipeId") is not None and not isinstance(value["recipeId"], str):
                raise ApplicationError("Task recipeId must be an ID string")
            task = {"id": task_id, "date": iso_date(value.get("date"), optional=True),
                    "title": text(value.get("title"), "Task title", 180),
                    "notes": text(value.get("notes"), "Task notes", optional=True),
                    "recipeId": value.get("recipeId") or None,
                    "servings": positive(value.get("servings"), "Servings", optional=True),
                    "mealIds": linked, "completedAt": old.get("completedAt"),
                    "stockOutputs": old.get("stockOutputs", [])}
            await recipe_snapshot(task)
            tasks.append(task)
        task_lookup = {task["id"]: task for task in tasks}
        entries = []
        for value in plan["entries"]:
            if not isinstance(value, dict) or not value.get("slot"):
                raise ApplicationError("Every plan entry must include a meal slot")
            entry_id = identity(value)
            old = previous.get(entry_id, {})
            slot = slots.get(text(value["slot"], "Meal slot", 80))
            if not slot or (not slot["enabled"] and old.get("slot") != slot["id"]):
                raise ApplicationError("Choose an enabled household meal slot")
            day = iso_date(value.get("date"))
            if not week <= date.fromisoformat(day) < week + timedelta(days=7):
                raise ApplicationError("Meal date must be in the selected week")
            values = value.get("components", [])
            if not isinstance(values, list) or len(values) > 30:
                raise ApplicationError("Meal components must be a list of at most 30 items")
            components = []
            for raw in values:
                item = component(raw)
                if item["id"] in component_ids:
                    raise ApplicationError("Component IDs must be unique")
                component_ids.add(item["id"])
                if item["pantryItemId"] and item["pantryItemId"] not in pantry:
                    raise ApplicationError("Pantry item was not found in this household")
                if item["taskId"]:
                    task = task_lookup.get(item["taskId"])
                    if not task:
                        raise ApplicationError("Component task was not found in this plan")
                    if task["date"] and task["date"] > day:
                        raise ApplicationError("A meal cannot use a task scheduled after the meal")
                await recipe_snapshot(item)
                components.append(item)
            source_meal = old.get("sourceMeal") if old else value.get("sourceMeal")
            if source_meal is not None and not old:
                if not isinstance(source_meal, dict):
                    raise ApplicationError("sourceMeal must identify a saved meal")
                origin = await self.meals.get(source_meal.get("id"))
                if origin.get("archivedAt") or source_meal != {
                        "id": origin["id"], "name": origin["name"], "revision": origin["revision"]}:
                    raise ApplicationError("Saved meal changed; read it again before planning")
            entries.append({"id": entry_id, "date": day, "day": date.fromisoformat(day).strftime("%A"),
                            "sourceMeal": source_meal,
                            "slot": slot["id"], "slotName": old.get("slotName", slot["name"]) if old.get("completedAt") else slot["name"],
                            "meal": text(value.get("meal"), "Meal name", 180),
                            "servings": positive(value.get("servings"), "Servings", optional=True),
                            "notes": text(value.get("notes"), "Meal notes", optional=True),
                            "components": components, "completedAt": old.get("completedAt")})
        entry_ids = {entry["id"] for entry in entries}
        if any(set(task["mealIds"]) - entry_ids for task in tasks):
            raise ApplicationError("Task meal link was not found in this plan")
        # Completed records are history. Edit future intentions without rewriting actual activity.
        for item in [*entries, *tasks]:
            old = previous.get(item["id"])
            if old and old.get("completedAt") and item != old:
                raise ApplicationError("Completed plan items cannot be edited")
        if any(old.get("completedAt") and old["id"] not in ids for old in previous.values()):
            raise ApplicationError("Completed plan items cannot be removed")
        if plan.get("ruleRevisionId"):
            await self.get_rules(plan["ruleRevisionId"])
        return await self.repository.save_meal_plan({**plan, "entries": entries, "tasks": tasks})

    async def update_plan_item(self, week_start: str, kind: str, item: dict) -> dict:
        self._week(week_start)
        if kind not in ("meal", "task"):
            raise ApplicationError("Item kind must be meal or task")
        if not isinstance(item, dict):
            raise ApplicationError("Plan item must be an object")
        plan = await self.repository.get_meal_plan(week_start) or {"weekStart": week_start, "entries": [], "tasks": []}
        key = "entries" if kind == "meal" else "tasks"
        current = next((row for row in plan.get(key, []) if row["id"] == item.get("id")), None)
        if item.get("id") and not current:
            raise ApplicationError("Plan item was not found")
        replacement = {**(current or {}), **item}
        plan[key] = [replacement if row is current else row for row in plan.get(key, [])]
        if current is None:
            plan[key].append(replacement)
        return await self.save_meal_plan(plan)

    async def complete_item(self, week_start: str, kind: str, item_id: str, inputs: list | None = None,
                            outputs: list | None = None) -> dict:
        self._week(week_start)
        if kind not in ("meal", "task"):
            raise ApplicationError("Item kind must be meal or task")
        plan = await self.repository.get_meal_plan(week_start)
        item = next((row for row in (plan or {}).get("entries" if kind == "meal" else "tasks", []) if row["id"] == item_id), None)
        if not item:
            raise ApplicationError("Plan item was not found")
        if item.get("completedAt"):
            return await self.repository.complete_plan_item(week_start, kind, item_id, [], [])
        inputs = [] if inputs is None else inputs
        outputs = [] if outputs is None else outputs
        if not isinstance(inputs, list) or not isinstance(outputs, list) or len(inputs) > 50 or len(outputs) > 30:
            raise ApplicationError("Activity inputs and outputs must be lists")
        pantry = {row["id"]: row for row in await self.repository.get_pantry()}
        cleaned_inputs, used_ids = [], set()
        for row in inputs:
            if not isinstance(row, dict) or row.get("itemId") not in pantry:
                raise ApplicationError("Pantry item was not found")
            if row["itemId"] in used_ids:
                raise ApplicationError("Combine repeated pantry inputs into one quantity")
            used_ids.add(row["itemId"])
            quantity = positive(row.get("quantity"))
            stock = pantry[row["itemId"]]
            if stock.get("quantity") is None or quantity > stock["quantity"]:
                raise ApplicationError("Not enough known pantry quantity; correct stock or actual use first")
            cleaned_inputs.append({"itemId": row["itemId"], "quantity": quantity})
        cleaned_outputs = []
        for row in outputs:
            if not isinstance(row, dict):
                raise ApplicationError("Each output must be an object")
            location = row.get("storageLocation", "fridge")
            if location not in ("pantry", "fridge", "freezer", "other"):
                raise ApplicationError("Invalid output storage location")
            if row.get("category") and row["category"] not in PANTRY_CATEGORIES:
                raise ApplicationError("Invalid output category")
            cleaned_outputs.append({"name": text(row.get("name"), "Output name", 160),
                                    "quantity": positive(row.get("quantity")),
                                    "unit": text(row.get("unit"), "Output unit", 40),
                                    "storageLocation": location,
                                    "category": row.get("category") or "uncategorized"})
        return await self.repository.complete_plan_item(week_start, kind, item_id, cleaned_inputs, cleaned_outputs)

    async def preview_shopping(self, week_start: str) -> dict:
        from .planning_demand import shopping_demand
        self._week(week_start)
        plan = await self.repository.get_meal_plan(week_start)
        if not plan:
            raise ApplicationError("Save a plan before calculating shopping needs")
        return shopping_demand(plan, await self.repository.get_pantry())

    async def save_plan_shopping(self, week_start: str) -> dict:
        preview = await self.preview_shopping(week_start)
        existing = await self.repository.get_shopping_list() or {}
        # Replace only pending suggestions for this week. Manual and purchased lines survive.
        keep = [row for row in existing.get("items", []) if row.get("purchased") or
                not ((row.get("source") or {}).get("generated") and (row.get("source") or {}).get("weekStart") == week_start)]
        saved = await self.repository.save_shopping_list({"id": existing.get("id"),
            "name": existing.get("name", "Weekly groceries"), "status": existing.get("status", "draft"),
            "mealPlanId": preview["mealPlanId"], "items": keep + preview["items"]})
        return {"shoppingList": saved, "warnings": preview["warnings"]}


class FeedbackService:
    FEEDBACK_TYPES = {"worked_well", "change_next_time", "problem", "preference_signal"}
    TAG_ALIASES = {
        "very-good": "worked-well",
        "great": "worked-well",
        "loved-it": "worked-well",
        "success": "worked-well",
        "didnt-work": "did-not-work",
        "preference": "preference-signal",
        "too-hot": "too-spicy",
        "children": "family:kids",
        "kids": "family:kids",
        "adults": "family:adults",
    }
    TAG_FACETS = {
        "worked-well": "outcome",
        "did-not-work": "outcome",
        "change-next-time": "outcome",
        "preference-signal": "outcome",
        "too-spicy": "taste",
        "too-salty": "taste",
        "bland": "taste",
        "too-dry": "texture",
        "too-soft": "texture",
        "crispy": "texture",
        "quick": "operations",
        "too-much-prep": "operations",
        "easy-cleanup": "operations",
        "successful-substitution": "adaptation",
        "serve-component-separately": "adaptation",
    }
    FEEDBACK_TYPE_TAG = {
        "worked_well": "worked-well",
        "change_next_time": "change-next-time",
        "problem": "did-not-work",
        "preference_signal": "preference-signal",
    }

    def __init__(self, repository: MealPrepRepository):
        self.repository = repository

    async def list(
        self,
        recipe_id: str | None = None,
        week_start: str | None = None,
        tags: list[str] | None = None,
        feedback_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if feedback_type == "preference":
            feedback_type = "preference_signal"
        if feedback_type not in self.FEEDBACK_TYPES | {None}:
            raise ApplicationError(
                "feedback_type must be worked_well, change_next_time, problem, or preference_signal"
            )
        normalized_tags = [tag["slug"] for tag in self._tag_records(tags or [])]
        return await self.repository.get_feedback(
            recipe_id=recipe_id,
            week_start=week_start,
            tags=normalized_tags,
            feedback_type=feedback_type,
            limit=min(max(limit, 1), 100),
        )

    async def save(self, feedback: dict[str, Any]) -> dict[str, Any]:
        note = str(feedback.get("note", "")).strip()
        if not note:
            raise ApplicationError("feedback.note is required")
        if len(note) > 600:
            raise ApplicationError("feedback.note must be 600 characters or fewer")
        if not any(
            feedback.get(key)
            for key in ("recipeId", "weekStart", "mealPlanEntryId", "occurrenceId")
        ):
            raise ApplicationError(
                "feedback must identify a recipe, week, meal-plan entry, or meal occurrence"
            )
        if feedback.get("occurrenceId") and feedback.get("mealPlanEntryId"):
            raise ApplicationError(
                "feedback must identify either an occurrenceId or a mealPlanEntryId, not both"
            )

        tag_records = self._tag_records(feedback.get("tags", []))
        tag_slugs = {tag["slug"] for tag in tag_records}
        feedback_type = feedback.get("feedbackType")
        if feedback_type == "preference":
            feedback_type = "preference_signal"
        if not feedback_type:
            if "worked-well" in tag_slugs:
                feedback_type = "worked_well"
            elif "did-not-work" in tag_slugs:
                feedback_type = "problem"
            else:
                feedback_type = "change_next_time"
        if feedback_type not in self.FEEDBACK_TYPES:
            raise ApplicationError(
                "feedback.feedbackType must be worked_well, change_next_time, problem, or preference_signal"
            )
        outcome_tag = self.FEEDBACK_TYPE_TAG[feedback_type]
        if outcome_tag not in tag_slugs:
            tag_records.extend(self._tag_records([outcome_tag]))
            tag_slugs.add(outcome_tag)
        if len(tag_records) > 12:
            raise ApplicationError("feedback.tags may contain at most 12 tags including its outcome")

        rating = feedback.get("rating")
        if rating is not None and (
            isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5
        ):
            raise ApplicationError("feedback.rating must be an integer from 1 to 5")

        next_time = str(feedback.get("nextTime", "")).strip()
        if len(next_time) > 600:
            raise ApplicationError("feedback.nextTime must be 600 characters or fewer")

        variant_name = str(feedback.get("variantName", "")).strip()
        adaptations = feedback.get("adaptations", [])
        if not isinstance(adaptations, list):
            raise ApplicationError("feedback.adaptations must be a list")
        if (variant_name or adaptations) and not (
            feedback.get("recipeId") or feedback.get("mealPlanEntryId") or feedback.get("occurrenceId")
        ):
            raise ApplicationError("A recipe-backed occurrence is required for a variant")

        normalized = {
            **feedback,
            "note": note,
            "feedbackType": feedback_type,
            "tags": [tag["slug"] for tag in tag_records],
            "tagRecords": tag_records,
            "nextTime": next_time,
            "variantName": variant_name,
            "adaptations": adaptations,
        }
        return await self.repository.save_feedback(normalized)

    async def what_worked(
        self,
        week_start: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        items = await self.list(
            week_start=week_start,
            tags=tags,
            feedback_type="worked_well",
            limit=limit,
        )
        tag_counts = Counter(
            tag["slug"]
            for item in items
            for tag in item.get("tags", [])
            if isinstance(tag, dict) and tag.get("slug") != "worked-well"
        )
        recipe_counts = Counter(
            (
                (item.get("occurrence") or {}).get("recipe_id"),
                (item.get("occurrence") or {}).get("title"),
            )
            for item in items
            if (item.get("occurrence") or {}).get("recipe_id")
        )
        return {
            "items": items,
            "count": len(items),
            "question": "what_worked",
            "tagSummary": [
                {"slug": slug, "count": count} for slug, count in tag_counts.most_common()
            ],
            "recipeSummary": [
                {"recipeId": recipe_id, "title": title, "count": count}
                for (recipe_id, title), count in recipe_counts.most_common()
            ],
        }

    async def recipe_feedback_summary(self, recipe_id: str, limit: int = 50) -> dict[str, Any]:
        recipe = await self.repository.get_recipe(recipe_id)
        if not recipe:
            raise ApplicationError("Recipe was not found")
        items = await self.list(recipe_id=recipe_id, limit=limit)
        tag_counts = Counter(
            tag["slug"]
            for item in items
            for tag in item.get("tags", [])
            if isinstance(tag, dict) and tag.get("slug")
        )
        variants: dict[str, dict[str, Any]] = {}
        for item in items:
            variant = (item.get("occurrence") or {}).get("variant")
            if variant and variant.get("id"):
                variants[variant["id"]] = variant
        return {
            "recipeId": recipe_id,
            "recipeTitle": recipe.get("title"),
            "evidenceCount": len(items),
            "workedWell": [item for item in items if item.get("feedback_type") == "worked_well"],
            "nextTime": [item for item in items if item.get("next_time")],
            "problems": [item for item in items if item.get("feedback_type") == "problem"],
            "preferenceSignals": [
                item for item in items if item.get("feedback_type") == "preference_signal"
            ],
            "tagSummary": [
                {"slug": slug, "count": count} for slug, count in tag_counts.most_common()
            ],
            "variants": list(variants.values()),
        }

    def _tag_records(self, tags: list[str]) -> list[dict[str, str]]:
        if not isinstance(tags, list):
            raise ApplicationError("feedback.tags must be a list")
        records: dict[str, dict[str, str]] = {}
        for value in tags:
            raw = str(value).strip().lower().replace("'", "")
            slug = re.sub(r"[^a-z0-9:_-]+", "-", raw.replace("_", "-")).strip("-")
            slug = self.TAG_ALIASES.get(slug, slug)
            if not slug or len(slug) > 48:
                raise ApplicationError("feedback tags must normalize to 1-48 characters")
            facet = (
                "audience"
                if slug.startswith("family:")
                else self.TAG_FACETS.get(slug, "other")
            )
            label = slug.split(":", 1)[-1].replace("-", " ").title()
            records[slug] = {"slug": slug, "label": label, "facet": facet}
        if len(records) > 12:
            raise ApplicationError("feedback.tags may contain at most 12 tags")
        return list(records.values())


class MemoryService:
    def __init__(self, repository: MealPrepRepository):
        self.repository = repository

    async def list(
        self,
        include_inactive: bool = False,
        status: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if status not in {None, "suggested", "confirmed", "forgotten"}:
            raise ApplicationError("status must be suggested, confirmed, or forgotten")
        if scope not in {None, "persistent", "this_week"}:
            raise ApplicationError("scope must be persistent or this_week")
        return await self.repository.get_household_memory(include_inactive, status, scope, limit)

    async def save(self, memory: dict[str, Any]) -> dict[str, Any]:
        if not str(memory.get("content", "")).strip():
            raise ApplicationError("memory.content is required")
        return await self.repository.save_household_memory(memory)

    async def review(self, memory_id: str, action: str, content: str | None = None) -> dict[str, Any]:
        if action not in {"confirm", "update", "forget"}:
            raise ApplicationError("action must be confirm, update, or forget")
        return await self.repository.review_household_memory(memory_id, action, content)


class ShoppingService:
    def __init__(self, repository: MealPrepRepository):
        self.repository = repository

    async def save(self, shopping_list: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(shopping_list.get("items"), list):
            raise ApplicationError("shopping_list.items is required")
        return await self.repository.save_shopping_list(shopping_list)

    async def get(self, list_id: str | None = None) -> dict[str, Any] | None:
        return await self.repository.get_shopping_list(list_id)

    async def add_item(self, item: dict[str, Any], list_id: str | None = None) -> dict[str, Any]:
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ApplicationError("item.name is required")
        store = item.get("store")
        if store is not None and not isinstance(store, str):
            raise ApplicationError("item.store must be a store name")
        quantity = item.get("quantity")
        if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0):
            raise ApplicationError("item.quantity must be positive")
        unit = item.get("unit")
        if unit is not None and not isinstance(unit, str):
            raise ApplicationError("item.unit must be text")
        normalized = {
            "name": name.strip(),
            "quantity": quantity,
            "unit": (unit.strip() or None) if isinstance(unit, str) else None,
            "store": (store.strip() or None) if isinstance(store, str) else None,
        }
        return await self.repository.add_shopping_item(normalized, list_id)

    async def mark_purchased(
        self,
        item_id: str,
        purchased: bool = True,
        purchased_quantity: float | None = None,
    ) -> dict[str, Any]:
        return await self.repository.mark_item_purchased(item_id, purchased, purchased_quantity)

    async def receive_item(self, item_id: str, quantity: float, unit: str, storage_location: str = "pantry") -> dict:
        amount = positive(quantity)
        unit = text(unit, "Received unit", 40)
        if storage_location not in ("pantry", "fridge", "freezer", "other"):
            raise ApplicationError("Invalid storage location")
        return await self.repository.receive_shopping_item(item_id, amount, unit, storage_location)


@dataclass(frozen=True)
class MealPrepServices:
    household: HouseholdService
    food: RecipePantryService
    planning: PlanningService
    feedback: FeedbackService
    memory: MemoryService
    shopping: ShoppingService
    circles: CircleService
