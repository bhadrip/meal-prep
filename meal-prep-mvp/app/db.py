from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token

from .config import Settings, get_settings


class RepositoryError(RuntimeError):
    pass


class SupabaseRepository:
    def __init__(self, settings: Settings, access_token: str):
        self.settings = settings
        self.access_token = access_token
        self.base_url = f"{settings.supabase_url.rstrip('/')}/rest/v1"

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.settings.supabase_anon_key,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
    ) -> Any:
        headers = self.headers
        if params and "on_conflict" in params:
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    params=params,
                    json=json,
                    headers=headers,
                )
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            detail = getattr(getattr(exc, "response", None), "text", "")
            raise RepositoryError(detail or str(exc)) from exc

    async def rpc(self, name: str, payload: dict[str, Any] | None = None) -> Any:
        return await self.request("POST", f"rpc/{name}", json=payload or {})

    async def bootstrap_household(self, name: str = "My household") -> str:
        value = await self.rpc("bootstrap_my_household", {"household_name": name})
        return str(value)

    async def household_id(self) -> str:
        context = await self.get_household_context(create_if_missing=True)
        return str(context["householdId"])

    async def get_household_context(self, *, create_if_missing: bool = True) -> dict[str, Any]:
        value = await self.rpc("get_household_context")
        if value is None and create_if_missing:
            await self.bootstrap_household()
            value = await self.rpc("get_household_context")
        if not isinstance(value, dict):
            raise RepositoryError("No household is available for this user")
        return value

    async def update_household_preferences(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "household_size": "householdSize",
            "dietary_restrictions": "dietaryRestrictions",
            "store_priority": "storePriority",
            "planning_preferences": "planningPreferences",
            "onboarding_completed_at": "onboardingCompletedAt",
        }
        row = {column: patch[key] for column, key in allowed.items() if key in patch}
        if not row:
            return await self.get_household_context()
        household_id = await self.household_id()
        await self.request(
            "PATCH",
            "household_preferences",
            params={"household_id": f"eq.{household_id}"},
            json=row,
        )
        return await self.get_household_context()

    async def search_recipes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        household_id = await self.household_id()
        params = {
            "select": "id,title,description,servings,active_minutes,total_minutes,tags,ingredients,instructions,source_url,created_at,updated_at",
            "household_id": f"eq.{household_id}",
            "archived_at": "is.null",
            "order": "updated_at.desc",
            "limit": str(min(max(limit, 1), 25)),
        }
        if query.strip():
            params["title"] = f"ilike.*{query.strip()[:80]}*"
        return await self.request("GET", "recipes", params=params) or []

    async def get_recipe(self, recipe_id: str) -> dict[str, Any] | None:
        rows = await self.request(
            "GET",
            "recipes",
            params={"select": "*", "id": f"eq.{recipe_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    async def save_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        household_id = await self.household_id()
        row = {
            "id": recipe.get("id") or str(uuid4()),
            "household_id": household_id,
            "title": recipe["title"],
            "description": recipe.get("description", ""),
            "servings": recipe.get("servings", 4),
            "active_minutes": recipe.get("activeMinutes"),
            "total_minutes": recipe.get("totalMinutes"),
            "tags": recipe.get("tags", []),
            "ingredients": recipe.get("ingredients", []),
            "instructions": recipe.get("instructions", []),
            "source_url": recipe.get("sourceUrl"),
            "source_type": recipe.get("sourceType", "manual"),
        }
        rows = await self.request(
            "POST", "recipes", params={"on_conflict": "id"}, json=row
        )
        return rows[0]

    async def archive_recipe(self, recipe_id: str) -> dict[str, Any]:
        rows = await self.request(
            "PATCH",
            "recipes",
            params={"id": f"eq.{recipe_id}"},
            json={"archived_at": datetime.now(UTC).isoformat()},
        )
        if not rows:
            raise RepositoryError("Recipe was not found")
        return rows[0]

    async def get_pantry(self) -> list[dict[str, Any]]:
        household_id = await self.household_id()
        return await self.request(
            "GET",
            "pantry_items",
            params={
                "select": "*",
                "household_id": f"eq.{household_id}",
                "order": "use_by_date.asc.nullslast,name.asc",
            },
        ) or []

    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]:
        household_id = await self.household_id()
        row = {
            "id": item.get("id") or str(uuid4()),
            "household_id": household_id,
            "name": item["name"],
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
            "storage_location": item.get("storageLocation", "pantry"),
            "quantity_confidence": item.get("quantityConfidence", "estimated"),
            "use_by_date": item.get("useByDate"),
            "freshness_basis": item.get("freshnessBasis"),
        }
        rows = await self.request(
            "POST", "pantry_items", params={"on_conflict": "id"}, json=row
        )
        return rows[0]

    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return await self.rpc("save_meal_plan", {"plan": plan})

    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None:
        value = await self.rpc("get_meal_plan", {"requested_week_start": week_start})
        return value if isinstance(value, dict) else None

    async def save_shopping_list(self, shopping_list: dict[str, Any]) -> dict[str, Any]:
        return await self.rpc("save_shopping_list", {"shopping_list": shopping_list})

    async def get_shopping_list(self, list_id: str | None = None) -> dict[str, Any] | None:
        value = await self.rpc("get_shopping_list", {"requested_list_id": list_id})
        return value if isinstance(value, dict) else None

    async def mark_item_purchased(
        self, item_id: str, purchased: bool, purchased_quantity: float | None = None
    ) -> dict[str, Any]:
        rows = await self.request(
            "PATCH",
            "shopping_items",
            params={"id": f"eq.{item_id}"},
            json={
                "purchased": purchased,
                "purchased_quantity": purchased_quantity,
                "purchased_at": datetime.now(UTC).isoformat() if purchased else None,
            },
        )
        if not rows:
            raise RepositoryError("Shopping item was not found")
        return rows[0]

    async def get_weekly_schedule(self, week_start: str | None = None) -> dict[str, Any] | None:
        household_id = await self.household_id()
        params = {
            "select": "id,week_start,days,is_normal_week,remember_rhythm,created_at,updated_at",
            "household_id": f"eq.{household_id}",
            "order": "week_start.desc",
            "limit": "1",
        }
        if week_start:
            params["week_start"] = f"eq.{week_start}"
        rows = await self.request("GET", "weekly_schedules", params=params)
        return rows[0] if rows else None

    async def save_weekly_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        household_id = await self.household_id()
        row = {
            "household_id": household_id,
            "week_start": schedule["weekStart"],
            "days": schedule["days"],
            "is_normal_week": schedule.get("isNormalWeek", True),
            "remember_rhythm": schedule.get("rememberRhythm", True),
        }
        rows = await self.request(
            "POST", "weekly_schedules", params={"on_conflict": "household_id,week_start"}, json=row
        )
        return rows[0]

    async def get_latest_retro(self) -> dict[str, Any] | None:
        household_id = await self.household_id()
        rows = await self.request(
            "GET", "weekly_retros",
            params={"select": "*", "household_id": f"eq.{household_id}", "order": "week_start.desc", "limit": "1"},
        )
        return rows[0] if rows else None

    async def save_weekly_retro(self, retro: dict[str, Any]) -> dict[str, Any]:
        household_id = await self.household_id()
        row = {
            "household_id": household_id,
            "week_start": retro["weekStart"],
            "outcomes": retro.get("outcomes", []),
            "worked_well": retro.get("workedWell", []),
            "stressors": retro.get("stressors", []),
            "note": str(retro.get("note", ""))[:600],
        }
        rows = await self.request(
            "POST", "weekly_retros", params={"on_conflict": "household_id,week_start"}, json=row
        )
        return rows[0]

    async def get_household_memory(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        household_id = await self.household_id()
        params = {
            "select": "*",
            "household_id": f"eq.{household_id}",
            "order": "status.desc,updated_at.desc",
        }
        if not include_inactive:
            params["active"] = "eq.true"
        return await self.request("GET", "household_memories", params=params) or []

    async def save_household_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        household_id = await self.household_id()
        row = {
            "id": memory.get("id") or str(uuid4()),
            "household_id": household_id,
            "category": memory.get("category", "planning"),
            "content": memory["content"],
            "source_type": memory.get("sourceType", "user"),
            "source_detail": memory.get("sourceDetail", "You told us"),
            "status": memory.get("status", "confirmed"),
            "scope": memory.get("scope", "persistent"),
            "evidence_count": memory.get("evidenceCount", 1),
            "active": memory.get("active", True),
        }
        rows = await self.request("POST", "household_memories", params={"on_conflict": "id"}, json=row)
        return rows[0]

    async def review_household_memory(self, memory_id: str, action: str, content: str | None = None) -> dict[str, Any]:
        patch: dict[str, Any]
        if action == "confirm":
            patch = {"status": "confirmed"}
        elif action == "forget":
            patch = {"active": False, "status": "forgotten"}
        elif action == "update" and content and content.strip():
            patch = {"content": content.strip()[:240], "status": "confirmed", "source_type": "user", "source_detail": "You corrected this"}
        else:
            raise RepositoryError("Unsupported memory review")
        rows = await self.request("PATCH", "household_memories", params={"id": f"eq.{memory_id}"}, json=patch)
        if not rows:
            raise RepositoryError("Memory was not found")
        return rows[0]


class DemoRepository:
    """Deterministic local state used when Supabase is not configured."""

    _context = {
        "householdId": "00000000-0000-0000-0000-000000000010",
        "householdName": "The Parkers",
        "householdSize": 4,
        "dietaryRestrictions": ["no shellfish"],
        "storePriority": [
            {"store": "Costco", "priority": 1},
            {"store": "Safeway", "priority": 2},
        ],
        "planningPreferences": {
            "weeknightMaxMinutes": 30,
            "leftoversForLunch": True,
        },
        "onboardingCompletedAt": "2026-01-01T00:00:00+00:00",
        "onboardingComplete": True,
    }
    _recipes = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "Paneer rice bowls",
            "description": "A fast bowl that uses spinach and roasted vegetables.",
            "servings": 4,
            "active_minutes": 20,
            "total_minutes": 28,
            "tags": ["vegetarian", "weeknight"],
            "ingredients": [
                {"name": "paneer", "quantity": 14, "unit": "oz"},
                {"name": "baby spinach", "quantity": 1, "unit": "bag"},
            ],
            "instructions": ["Cook rice.", "Sear paneer.", "Assemble bowls."],
        }
    ]
    _pantry = [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Baby spinach",
            "quantity": 1,
            "unit": "bag",
            "storage_location": "fridge",
            "quantity_confidence": "exact",
            "use_by_date": date.today().isoformat(),
        }
    ]
    _meal_plan = {
        "id": "33333333-3333-3333-3333-333333333333",
        "weekStart": date.today().isoformat(),
        "status": "draft",
        "entries": [
            {"day": "Monday", "meal": "Tomato pasta", "servings": 4},
            {"day": "Tuesday", "meal": "Paneer rice bowls", "servings": 4},
            {"day": "Wednesday", "meal": "Lemon chicken tray bake", "servings": 4},
        ],
    }
    _shopping_list = {
        "id": "44444444-4444-4444-4444-444444444444",
        "name": "Weekly groceries",
        "status": "draft",
        "items": [
            {"id": "55555555-5555-5555-5555-555555555551", "name": "Paneer", "quantity": 2, "unit": "packs", "store": "Costco", "purchased": False},
            {"id": "55555555-5555-5555-5555-555555555552", "name": "Cilantro", "quantity": 1, "unit": "bunch", "store": "Safeway", "purchased": False},
        ],
    }
    _weekly_schedule = {
        "id": "66666666-6666-6666-6666-666666666666",
        "week_start": date.today().isoformat(),
        "days": [
            {"day": "Monday", "mode": "quick"}, {"day": "Tuesday", "mode": "cook"},
            {"day": "Wednesday", "mode": "quick"}, {"day": "Thursday", "mode": "leftovers"},
            {"day": "Friday", "mode": "flexible"}, {"day": "Saturday", "mode": "cook"},
            {"day": "Sunday", "mode": "prep"},
        ],
        "is_normal_week": True,
        "remember_rhythm": True,
    }
    _latest_retro = None
    _memories = [
        {
            "id": "77777777-7777-7777-7777-777777777777",
            "category": "success", "content": "Planned leftovers work well", "source_type": "user",
            "source_detail": "You told us", "status": "confirmed", "scope": "persistent",
            "evidence_count": 1, "active": True,
        }
    ]

    async def get_household_context(self, **_: Any) -> dict[str, Any]:
        return deepcopy(self._context)

    async def update_household_preferences(self, patch: dict[str, Any]) -> dict[str, Any]:
        self._context.update(deepcopy(patch))
        return deepcopy(self._context)

    async def search_recipes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        matches = [item for item in self._recipes if query.lower() in item["title"].lower()]
        return deepcopy(matches[:limit])

    async def get_recipe(self, recipe_id: str) -> dict[str, Any] | None:
        return deepcopy(next((item for item in self._recipes if item["id"] == recipe_id), None))

    async def save_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        row = {"id": recipe.get("id") or str(uuid4()), **deepcopy(recipe)}
        self._recipes = [item for item in self._recipes if item["id"] != row["id"]] + [row]
        return deepcopy(row)

    async def archive_recipe(self, recipe_id: str) -> dict[str, Any]:
        row = await self.get_recipe(recipe_id)
        if not row:
            raise RepositoryError("Recipe was not found")
        row["archived_at"] = datetime.now(UTC).isoformat()
        return row

    async def get_pantry(self) -> list[dict[str, Any]]:
        return deepcopy(self._pantry)

    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]:
        row = {"id": item.get("id") or str(uuid4()), **deepcopy(item)}
        self._pantry = [value for value in self._pantry if value["id"] != row["id"]] + [row]
        return deepcopy(row)

    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        self._meal_plan = {"id": plan.get("id") or str(uuid4()), **deepcopy(plan)}
        return deepcopy(self._meal_plan)

    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None:
        return deepcopy(self._meal_plan)

    async def save_shopping_list(self, shopping_list: dict[str, Any]) -> dict[str, Any]:
        self._shopping_list = {"id": shopping_list.get("id") or str(uuid4()), **deepcopy(shopping_list)}
        return deepcopy(self._shopping_list)

    async def get_shopping_list(self, list_id: str | None = None) -> dict[str, Any] | None:
        return deepcopy(self._shopping_list)

    async def mark_item_purchased(
        self, item_id: str, purchased: bool, purchased_quantity: float | None = None
    ) -> dict[str, Any]:
        item = next((item for item in self._shopping_list["items"] if item["id"] == item_id), None)
        if not item:
            raise RepositoryError("Shopping item was not found")
        item["purchased"] = purchased
        item["purchasedQuantity"] = purchased_quantity
        return deepcopy(item)

    async def get_weekly_schedule(self, week_start: str | None = None) -> dict[str, Any] | None:
        value = type(self)._weekly_schedule
        if week_start and value.get("week_start") != week_start:
            return None
        return deepcopy(value)

    async def save_weekly_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        value = {
            "id": type(self)._weekly_schedule.get("id") or str(uuid4()),
            "week_start": schedule["weekStart"],
            "days": deepcopy(schedule["days"]),
            "is_normal_week": schedule.get("isNormalWeek", True),
            "remember_rhythm": schedule.get("rememberRhythm", True),
        }
        type(self)._weekly_schedule = value
        return deepcopy(value)

    async def get_latest_retro(self) -> dict[str, Any] | None:
        return deepcopy(type(self)._latest_retro)

    async def save_weekly_retro(self, retro: dict[str, Any]) -> dict[str, Any]:
        value = {
            "id": str(uuid4()),
            "week_start": retro["weekStart"],
            "outcomes": deepcopy(retro.get("outcomes", [])),
            "worked_well": deepcopy(retro.get("workedWell", [])),
            "stressors": deepcopy(retro.get("stressors", [])),
            "note": str(retro.get("note", ""))[:600],
        }
        type(self)._latest_retro = value
        return deepcopy(value)

    async def get_household_memory(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        items = type(self)._memories
        return deepcopy(items if include_inactive else [item for item in items if item.get("active", True)])

    async def save_household_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        value = {
            "id": memory.get("id") or str(uuid4()), "category": memory.get("category", "planning"),
            "content": memory["content"], "source_type": memory.get("sourceType", "user"),
            "source_detail": memory.get("sourceDetail", "You told us"), "status": memory.get("status", "confirmed"),
            "scope": memory.get("scope", "persistent"), "evidence_count": memory.get("evidenceCount", 1),
            "active": memory.get("active", True),
        }
        type(self)._memories = [item for item in type(self)._memories if item["id"] != value["id"]] + [value]
        return deepcopy(value)

    async def review_household_memory(self, memory_id: str, action: str, content: str | None = None) -> dict[str, Any]:
        item = next((item for item in type(self)._memories if item["id"] == memory_id), None)
        if not item:
            raise RepositoryError("Memory was not found")
        if action == "confirm":
            item["status"] = "confirmed"
        elif action == "forget":
            item.update({"active": False, "status": "forgotten"})
        elif action == "update" and content and content.strip():
            item.update({"content": content.strip()[:240], "status": "confirmed", "source_type": "user", "source_detail": "You corrected this"})
        else:
            raise RepositoryError("Unsupported memory review")
        return deepcopy(item)


def repository_for_request() -> SupabaseRepository | DemoRepository:
    settings = get_settings()
    if not settings.supabase_configured:
        return DemoRepository()
    access = get_access_token()
    if not access:
        if settings.auth_required:
            raise RepositoryError("Authentication is required")
        return DemoRepository()
    return SupabaseRepository(settings, access.token)
