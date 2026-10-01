from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import re
from typing import Any, Awaitable, Callable, Protocol
from uuid import UUID

from .errors import ApplicationError, RepositoryError, StorageNotInstalledError
from .pantry_photos import compact_photo, download_chatgpt_photo, normalize_observations
from .pantry_categories import PANTRY_CATEGORIES, infer_pantry_category


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
        return await self.repository.get_household_context()

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
            "pantry": self.repository.get_pantry,
            "recipes": lambda: self.repository.search_recipes(query="", limit=25),
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
        household = await self.repository.get_household_context()
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
                                   max_minutes: int | None = None, limit: int = 25, offset: int = 0) -> dict:
        from .recipe_browsing import browse
        return browse(await self.repository.get_recipe_graph_data(), query, filters, max_minutes, limit, offset)

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
        clean = {**recipe, "tags": tags}
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

    async def revoke_recipe_share(self, share_id: str) -> dict[str, Any]:
        if not await self.repository.revoke_recipe_share(share_id):
            raise ApplicationError("Share was not found")
        return {"id": share_id, "revoked": True}

    async def copy_shared_recipe(self, token: str) -> dict[str, Any]:
        return {"recipeId": await self.repository.copy_shared_recipe(token)}

    async def get_pantry(self) -> list[dict[str, Any]]:
        return await self.repository.get_pantry()

    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if not str(item.get("name", "")).strip():
            raise ApplicationError("item.name is required")
        category = item.get("category")
        if category is not None and category not in PANTRY_CATEGORIES:
            raise ApplicationError("Invalid pantry category")
        if category is None:
            existing = next((row for row in await self.repository.get_pantry() if row.get("id") == item.get("id")), None) if item.get("id") else None
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

    async def get_context(self, week_start: str | None = None) -> dict[str, Any]:
        if week_start:
            self._week(week_start)
        household = await self.repository.get_household_context()
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
            "pantry": self.repository.get_pantry(),
            "recipeTags": self.repository.list_recipe_tags(),
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
        missing_slot = [entry for entry in plan["entries"] if not entry.get("slot")]
        if missing_slot:
            raise ApplicationError("Every plan entry must include a meal slot")
        if plan.get("ruleRevisionId"):
            await self.get_rules(plan["ruleRevisionId"])
        return await self.repository.save_meal_plan(plan)


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


@dataclass(frozen=True)
class MealPrepServices:
    household: HouseholdService
    food: RecipePantryService
    planning: PlanningService
    feedback: FeedbackService
    memory: MemoryService
    shopping: ShoppingService
