from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Protocol

from .errors import ApplicationError, RepositoryError


class MealPrepRepository(Protocol):
    async def get_household_context(self, *, create_if_missing: bool = True) -> dict[str, Any]: ...
    async def update_household_preferences(self, patch: dict[str, Any]) -> dict[str, Any]: ...
    async def search_recipes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]: ...
    async def get_recipe(self, recipe_id: str) -> dict[str, Any] | None: ...
    async def save_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]: ...
    async def archive_recipe(self, recipe_id: str) -> dict[str, Any]: ...
    async def get_pantry(self) -> list[dict[str, Any]]: ...
    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]: ...
    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]: ...
    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None: ...
    async def save_shopping_list(self, shopping_list: dict[str, Any]) -> dict[str, Any]: ...
    async def get_shopping_list(self, list_id: str | None = None) -> dict[str, Any] | None: ...
    async def mark_item_purchased(
        self,
        item_id: str,
        purchased: bool = True,
        purchased_quantity: float | None = None,
    ) -> dict[str, Any]: ...
    async def get_weekly_schedule(self, week_start: str | None = None) -> dict[str, Any] | None: ...
    async def save_weekly_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]: ...
    async def get_latest_retro(self, before_week_start: str | None = None) -> dict[str, Any] | None: ...
    async def get_weekly_retro(self, week_start: str | None = None) -> dict[str, Any] | None: ...
    async def save_weekly_retro(self, retro: dict[str, Any]) -> dict[str, Any]: ...
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

    async def snapshot(self) -> dict[str, Any]:
        async def section(loader: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
            try:
                value = await loader()
            except RepositoryError:
                return {"status": "unavailable", "value": None}
            empty = value is None or value == [] or value == {}
            return {"status": "empty" if empty else "ready", "value": value}

        household = await self.repository.get_household_context()
        return {
            "household": household,
            "sections": {
                "pantry": await section(self.repository.get_pantry),
                "recipes": await section(lambda: self.repository.search_recipes(query="", limit=25)),
                "schedule": await section(self.repository.get_weekly_schedule),
                "memories": await section(self.repository.get_household_memory),
                "mealPlan": await section(self.repository.get_meal_plan),
                "shoppingList": await section(self.repository.get_shopping_list),
            },
        }


class RecipePantryService:
    def __init__(self, repository: MealPrepRepository):
        self.repository = repository

    async def search_recipes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        return await self.repository.search_recipes(query=query, limit=limit)

    async def get_recipe(self, recipe_id: str) -> dict[str, Any]:
        recipe = await self.repository.get_recipe(recipe_id)
        if not recipe:
            raise ApplicationError("Recipe was not found")
        return recipe

    async def save_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        if not str(recipe.get("title", "")).strip():
            raise ApplicationError("recipe.title is required")
        return await self.repository.save_recipe(recipe)

    async def archive_recipe(self, recipe_id: str) -> dict[str, Any]:
        return await self.repository.archive_recipe(recipe_id)

    async def get_pantry(self) -> list[dict[str, Any]]:
        return await self.repository.get_pantry()

    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if not str(item.get("name", "")).strip():
            raise ApplicationError("item.name is required")
        return await self.repository.update_pantry_item(item)


class PlanningService:
    def __init__(self, repository: MealPrepRepository):
        self.repository = repository

    async def get_context(self, week_start: str | None = None) -> dict[str, Any]:
        return {
            "household": await self.repository.get_household_context(),
            "schedule": await self.repository.get_weekly_schedule(week_start),
            "retro": await self.repository.get_latest_retro(before_week_start=week_start),
            "memories": await self.repository.get_household_memory(),
            "requestedWeekStart": week_start,
        }

    async def get_schedule(self, week_start: str | None = None) -> dict[str, Any] | None:
        return await self.repository.get_weekly_schedule(week_start)

    async def save_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        if not schedule.get("weekStart") or len(schedule.get("days", [])) != 7:
            raise ApplicationError("schedule.weekStart and seven schedule.days are required")
        return await self.repository.save_weekly_schedule(schedule)

    async def get_latest_retro(self) -> dict[str, Any] | None:
        return await self.repository.get_latest_retro()

    async def get_retro(self, week_start: str | None = None) -> dict[str, Any] | None:
        return await self.repository.get_weekly_retro(week_start)

    async def save_retro(self, retro: dict[str, Any]) -> dict[str, Any]:
        if not retro.get("weekStart") or not isinstance(retro.get("outcomes", []), list):
            raise ApplicationError("retro.weekStart and retro.outcomes are required")
        return await self.repository.save_weekly_retro(retro)

    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None:
        return await self.repository.get_meal_plan(week_start)

    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        if not plan.get("weekStart") or not isinstance(plan.get("entries"), list):
            raise ApplicationError("plan.weekStart and plan.entries are required")
        missing_slot = [entry for entry in plan["entries"] if not entry.get("slot")]
        if missing_slot:
            raise ApplicationError("Every plan entry must include a meal slot")
        return await self.repository.save_meal_plan(plan)


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
    memory: MemoryService
    shopping: ShoppingService
