from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from secrets import token_hex
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token

from ..application.errors import RepositoryError, RevisionConflictError, StorageNotInstalledError
from ..application.pantry_categories import infer_pantry_category
from ..config import Settings, get_settings


PLANNING_TABLES = {
    "weekly_schedules": "weekly schedules",
    "feedback_entries": "feedback",
    "household_memories": "household preferences",
    "meal_plan_rule_revisions": "meal plan rules",
}
PLANNING_FUNCTIONS = {
    "rpc/get_experience_feedback": "feedback",
    "rpc/save_experience_feedback": "feedback",
    "rpc/record_pantry_use": "pantry use",
    "rpc/save_meal_plan_rules": "meal plan rules",
    "rpc/get_recent_meal_plans": "planning history",
}


def _repository_error(path: str, exc: httpx.HTTPError | ValueError) -> RepositoryError | RevisionConflictError:
    response = getattr(exc, "response", None)
    detail = getattr(response, "text", "")
    if response is not None:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("details") or detail)
            code = payload.get("code")
            table = path.split("?", 1)[0].strip("/")
            if table == "rpc/save_meal_plan_rules" and code == "P0001" and detail.startswith("Meal plan rules changed."):
                return RevisionConflictError(detail)
            if code == "PGRST205" and table in PLANNING_TABLES:
                return StorageNotInstalledError(PLANNING_TABLES[table])
            if code == "PGRST202" and table in PLANNING_FUNCTIONS:
                return StorageNotInstalledError(PLANNING_FUNCTIONS[table])
    return RepositoryError(detail or str(exc))


class SupabaseRepository:
    def __init__(self, settings: Settings, access_token: str):
        self.settings = settings
        self.access_token = access_token
        self.base_url = f"{settings.supabase_url.rstrip('/')}/rest/v1"
        self._household_context: dict[str, Any] | None = None

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
            raise _repository_error(path, exc) from exc

    async def rpc(self, name: str, payload: dict[str, Any] | None = None) -> Any:
        return await self.request("POST", f"rpc/{name}", json=payload or {})

    async def bootstrap_household(self, name: str = "My household") -> str:
        value = await self.rpc("bootstrap_my_household", {"household_name": name})
        return str(value)

    async def household_id(self) -> str:
        context = await self.get_household_context(create_if_missing=True)
        return str(context["householdId"])

    async def get_household_context(self, *, create_if_missing: bool = True) -> dict[str, Any]:
        if self._household_context is not None:
            return deepcopy(self._household_context)
        value = await self.rpc("get_household_context")
        if value is None and create_if_missing:
            await self.bootstrap_household()
            value = await self.rpc("get_household_context")
        if not isinstance(value, dict):
            raise RepositoryError("No household is available for this user")
        self._household_context = value
        return deepcopy(value)

    async def list_households(self) -> dict[str, Any]:
        return await self.rpc("list_my_households")

    async def switch_household(self, household_id: str) -> dict[str, Any]:
        result = await self.rpc("set_active_household", {"requested_household_id": household_id})
        self._household_context = None
        return result

    async def create_household(self, name: str) -> dict[str, Any]:
        result = await self.rpc("create_my_household", {"requested_name": name})
        self._household_context = None
        return result

    async def update_household_preferences(
        self, patch: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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
        household_id = str(context["householdId"]) if context is not None else await self.household_id()
        rows = await self.request(
            "PATCH",
            "household_preferences",
            params={"household_id": f"eq.{household_id}"},
            json=row,
        )
        if not rows:
            raise RepositoryError("Household preferences were not saved")
        if context is not None and set(row) == {"planning_preferences"}:
            updated = {**context, "planningPreferences": rows[0]["planning_preferences"]}
            self._household_context = updated
            return updated
        self._household_context = None
        return await self.get_household_context()

    async def search_recipes(self, query: str = "", limit: int = 10, tag: str = "") -> list[dict[str, Any]]:
        household_id = await self.household_id()
        params = {
            "select": "id,title,description,servings,active_minutes,total_minutes,tags,ingredients,instructions,source_url,created_at,updated_at",
            "household_id": f"eq.{household_id}",
            "archived_at": "is.null",
            "order": "updated_at.desc",
            "limit": str(min(max(limit, 1), 25)),
        }
        if not query.strip() and not tag:
            return await self.request("GET", "recipes", params=params) or []
        return await self.rpc("find_recipes", {
            "search_query": query.strip()[:80], "filter_tag": tag,
            "result_limit": min(max(limit, 1), 25),
        }) or []

    async def list_recipe_tags(self) -> list[dict[str, Any]]:
        return await self.rpc("list_recipe_tags") or []

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

    async def create_recipe_share(self, recipe_id: str, expires_at: str | None = None) -> dict[str, Any]:
        return await self.rpc("create_recipe_share", {
            "requested_recipe_id": recipe_id,
            "requested_expires_at": expires_at,
        })

    async def list_recipe_shares(self) -> list[dict[str, Any]]:
        return await self.rpc("list_recipe_shares") or []

    async def revoke_recipe_share(self, share_id: str) -> bool:
        return bool(await self.rpc("revoke_recipe_share", {"requested_share_id": share_id}))

    async def copy_shared_recipe(self, token: str) -> str:
        await self.household_id()
        return str(await self.rpc("copy_shared_recipe", {"raw_token": token}))

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
            "category": item.get("category") or infer_pantry_category(item["name"], item.get("storageLocation", "pantry")),
            "quantity_confidence": item.get("quantityConfidence", "estimated"),
            "use_by_date": item.get("useByDate"),
            "freshness_basis": item.get("freshnessBasis"),
            "provenance": item.get("provenance", {}),
        }
        rows = await self.request(
            "POST", "pantry_items", params={"on_conflict": "id"}, json=row
        )
        return rows[0]

    async def record_pantry_use(
        self, item_id: str, quantity: float, recipe_id: str | None = None,
        meal_title: str | None = None,
    ) -> dict[str, Any]:
        await self.household_id()
        return await self.rpc("record_pantry_use", {
            "requested_item_id": item_id,
            "amount_used": quantity,
            "requested_recipe_id": recipe_id,
            "requested_meal_title": meal_title,
        })

    async def save_pantry_photo(
        self, *, image: bytes, width: int, height: int,
        file_id: str, note: str, observations: list[dict[str, Any]],
        apply_to_pantry: bool,
    ) -> dict[str, Any]:
        household_id = await self.household_id()
        evidence_id = str(uuid4())
        object_path = f"{household_id}/{evidence_id}.webp"
        storage_url = f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/pantry-evidence/{object_path}"
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(
                    storage_url,
                    content=image,
                    headers={
                        "apikey": self.settings.supabase_anon_key,
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "image/webp",
                        "cache-control": "3600",
                        "x-upsert": "false",
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise _repository_error("pantry-evidence upload", exc) from exc
        try:
            rows = await self.request("POST", "pantry_photo_evidence", json={
                "id": evidence_id,
                "household_id": household_id,
                "object_path": object_path,
                "source_file_id": file_id[:200],
                "note": note[:1000],
                "observations": observations,
                "image_bytes": len(image),
                "image_width": width,
                "image_height": height,
                "status": "captured",
            })
        except RepositoryError:
            await self._remove_photo_object(object_path)
            raise
        evidence = rows[0]
        if apply_to_pantry:
            applied = []
            for observation in observations:
                item = {**observation, "provenance": {
                    "sourceType": "pantry_photo",
                    "evidenceId": evidence_id,
                }}
                saved = await self.update_pantry_item(item)
                applied.append(saved["id"])
            rows = await self.request("PATCH", "pantry_photo_evidence", params={"id": f"eq.{evidence_id}"}, json={
                "applied_item_ids": applied,
                "status": "applied",
            })
            evidence = rows[0]
        return evidence

    async def _remove_photo_object(self, object_path: str) -> None:
        url = f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/pantry-evidence/{object_path}"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                await client.delete(url, headers={
                    "apikey": self.settings.supabase_anon_key,
                    "Authorization": f"Bearer {self.access_token}",
                })
        except httpx.HTTPError:
            pass

    async def get_pantry_photos(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        household_id = await self.household_id()
        rows = await self.request("GET", "pantry_photo_evidence", params={
            "select": "id,created_at,note,observations,image_bytes,image_width,image_height,status,applied_item_ids,object_path",
            "household_id": f"eq.{household_id}",
            "order": "created_at.desc",
            "limit": str(min(max(limit, 1), 100)),
            "offset": str(max(offset, 0)),
        }) or []
        for row in rows:
            path = quote(row.pop("object_path"), safe="/")
            url = f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/sign/pantry-evidence/{path}"
            try:
                async with httpx.AsyncClient(timeout=12) as client:
                    response = await client.post(url, json={"expiresIn": 3600}, headers=self.headers)
                    response.raise_for_status()
                    signed = response.json().get("signedURL") or response.json().get("signedUrl")
                row["image_url"] = f"{self.settings.supabase_url.rstrip('/')}/storage/v1{signed}" if signed and signed.startswith("/") else signed
            except (httpx.HTTPError, ValueError):
                row["image_url"] = None
        return rows

    async def apply_pantry_photo(
        self, evidence_id: str, observations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            UUID(evidence_id)
        except ValueError as exc:
            raise RepositoryError("Invalid pantry photo evidence ID") from exc
        household_id = await self.household_id()
        rows = await self.request("GET", "pantry_photo_evidence", params={
            "select": "*", "id": f"eq.{evidence_id}",
            "household_id": f"eq.{household_id}", "limit": "1",
        })
        if not rows:
            raise RepositoryError("Pantry photo evidence was not found")
        evidence = rows[0]
        if evidence["status"] == "applied":
            raise RepositoryError("This pantry photo has already been applied")
        chosen = observations if observations is not None else evidence["observations"]
        applied = []
        for observation in chosen:
            saved = await self.update_pantry_item({**observation, "provenance": {
                "sourceType": "pantry_photo", "evidenceId": evidence_id,
            }})
            applied.append(saved["id"])
        updated = await self.request("PATCH", "pantry_photo_evidence", params={"id": f"eq.{evidence_id}"}, json={
            "observations": chosen, "applied_item_ids": applied, "status": "applied",
        })
        return updated[0]

    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return await self.rpc("save_meal_plan", {"plan": plan})

    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None:
        value = await self.rpc("get_meal_plan", {"requested_week_start": week_start})
        return value if isinstance(value, dict) else None

    async def get_recent_meal_plans(self, before_week: str, limit: int = 2) -> list[dict[str, Any]]:
        return await self.rpc("get_recent_meal_plans", {"before_week": before_week, "result_limit": limit}) or []

    @staticmethod
    def _rule_document(row: dict[str, Any]) -> dict[str, Any]:
        return {"id": row["id"], "revision": row["revision"], "text": row["text"], "createdAt": row["created_at"]}

    async def get_meal_plan_rules(self, revision_id: str | None = None) -> dict[str, Any] | None:
        params = {"select": "id,revision,text,created_at", "household_id": f"eq.{await self.household_id()}",
                  "order": "revision.desc", "limit": "1"}
        if revision_id:
            params["id"] = f"eq.{revision_id}"
        rows = await self.request("GET", "meal_plan_rule_revisions", params=params)
        return self._rule_document(rows[0]) if rows else None

    async def get_meal_plan_rule_history(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.request("GET", "meal_plan_rule_revisions", params={
            "select": "id,revision,text,created_at", "household_id": f"eq.{await self.household_id()}",
            "order": "revision.desc", "limit": str(limit),
        })
        return [self._rule_document(row) for row in rows or []]

    async def save_meal_plan_rules(self, text: str, expected_revision: int) -> dict[str, Any]:
        return await self.rpc("save_meal_plan_rules", {"rule_text": text, "expected_revision": expected_revision})

    async def save_shopping_list(self, shopping_list: dict[str, Any]) -> dict[str, Any]:
        return await self.rpc("save_shopping_list", {"shopping_list": shopping_list})

    async def get_shopping_list(self, list_id: str | None = None) -> dict[str, Any] | None:
        value = await self.rpc("get_shopping_list", {"requested_list_id": list_id})
        return value if isinstance(value, dict) else None

    async def add_shopping_item(self, item: dict[str, Any], list_id: str | None = None) -> dict[str, Any]:
        return await self.rpc("add_shopping_item", {"item": item, "requested_list_id": list_id})

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
            "select": "id,week_start,days,notes,is_normal_week,remember_rhythm,created_at,updated_at",
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
        if "notes" in schedule:
            row["notes"] = schedule["notes"].strip()
        rows = await self.request(
            "POST", "weekly_schedules", params={"on_conflict": "household_id,week_start"}, json=row
        )
        return rows[0]

    async def get_feedback(
        self,
        recipe_id: str | None = None,
        week_start: str | None = None,
        tags: list[str] | None = None,
        feedback_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        value = await self.rpc(
            "get_experience_feedback",
            {
                "requested_recipe_id": recipe_id,
                "requested_week_start": week_start,
                "requested_tags": tags or None,
                "requested_feedback_type": feedback_type,
                "result_limit": min(max(limit, 1), 100),
            },
        )
        return value if isinstance(value, list) else []

    async def save_feedback(self, feedback: dict[str, Any]) -> dict[str, Any]:
        value = await self.rpc("save_experience_feedback", {"feedback": feedback})
        if not isinstance(value, dict):
            raise RepositoryError("Feedback could not be saved")
        return value

    async def get_household_memory(
        self,
        include_inactive: bool = False,
        status: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        household_id = await self.household_id()
        params = {
            "select": "*",
            "household_id": f"eq.{household_id}",
            "order": "status.desc,updated_at.desc",
            "limit": str(min(max(limit, 1), 100)),
        }
        if not include_inactive:
            params["active"] = "eq.true"
        if status:
            params["status"] = f"eq.{status}"
        if scope:
            params["scope"] = f"eq.{scope}"
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
            "status": memory.get("status", "suggested"),
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

    def __init__(self) -> None:
        initial_plan = deepcopy(self._meal_plan)
        for entry in initial_plan["entries"]:
            entry["id"] = entry.get("id") or str(uuid4())
        self._meal_plans = {initial_plan["weekStart"]: initial_plan}
        self._rule_revisions: list[dict[str, Any]] = []
        initial_schedule = deepcopy(self._weekly_schedule)
        self._weekly_schedules = {initial_schedule["week_start"]: initial_schedule}

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
    _shares: dict[str, dict[str, Any]] = {}
    _pantry = [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Baby spinach",
            "quantity": 1,
            "unit": "bag",
            "storage_location": "fridge",
            "category": "vegetables",
            "quantity_confidence": "exact",
            "use_by_date": date.today().isoformat(),
        }
    ]
    _pantry_photos: list[dict[str, Any]] = []
    _meal_plan = {
        "id": "33333333-3333-3333-3333-333333333333",
        "weekStart": (date.today() - timedelta(days=date.today().weekday())).isoformat(),
        "status": "draft",
        "entries": [
            {"day": "Monday", "slot": "dinner", "meal": "Tomato pasta", "servings": 4},
            {"day": "Tuesday", "slot": "dinner", "meal": "Paneer rice bowls", "servings": 4},
            {"day": "Wednesday", "slot": "dinner", "meal": "Lemon chicken tray bake", "servings": 4},
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
        "week_start": (date.today() - timedelta(days=date.today().weekday())).isoformat(),
        "days": [
            {"day": "Monday", "mode": "quick"}, {"day": "Tuesday", "mode": "cook"},
            {"day": "Wednesday", "mode": "quick"}, {"day": "Thursday", "mode": "leftovers"},
            {"day": "Friday", "mode": "flexible"}, {"day": "Saturday", "mode": "cook"},
            {"day": "Sunday", "mode": "prep"},
        ],
        "is_normal_week": True,
        "remember_rhythm": True,
    }
    _feedback: list[dict[str, Any]] = []
    _occurrences: list[dict[str, Any]] = []
    _variants: list[dict[str, Any]] = []
    _feedback_tags: list[dict[str, Any]] = []
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

    async def list_households(self) -> dict[str, Any]:
        return {"activeHouseholdId": self._context["householdId"], "households": [{"id": self._context["householdId"], "name": self._context["householdName"], "role": "owner"}]}

    async def switch_household(self, household_id: str) -> dict[str, Any]:
        if household_id != self._context["householdId"]:
            raise RepositoryError("Household is not available in demo mode")
        return await self.list_households()

    async def create_household(self, name: str) -> dict[str, Any]:
        raise RepositoryError("Creating households requires Supabase")

    async def update_household_preferences(
        self, patch: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._context.update(deepcopy(patch))
        return deepcopy(self._context)

    async def search_recipes(self, query: str = "", limit: int = 10, tag: str = "") -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        matches = [item for item in self._recipes if (
            not tag or tag in [str(value).casefold() for value in item.get("tags", [])]
        ) and (
            not needle or any(needle in str(item.get(key) or "").casefold() for key in ("title", "description"))
            or any(needle in str(value).casefold() for value in item.get("tags", []))
        )]
        return deepcopy(matches[:limit])

    async def list_recipe_tags(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for recipe in self._recipes:
            for tag in set(str(value).strip().casefold() for value in recipe.get("tags", []) if str(value).strip()):
                counts[tag] = counts.get(tag, 0) + 1
        return [{"tag": tag, "recipe_count": count} for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]

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
        self._recipes = [item for item in self._recipes if item["id"] != recipe_id]
        return row

    async def create_recipe_share(self, recipe_id: str, expires_at: str | None = None) -> dict[str, Any]:
        recipe = await self.get_recipe(recipe_id)
        if not recipe or recipe.get("archived_at"):
            raise RepositoryError("Recipe was not found")
        token = token_hex(32)
        share_id = str(uuid4())
        snapshot = {
            key: deepcopy(recipe.get(source))
            for key, source in {
                "title": "title", "description": "description", "servings": "servings",
                "activeMinutes": "active_minutes", "totalMinutes": "total_minutes",
                "tags": "tags", "ingredients": "ingredients", "instructions": "instructions",
                "sourceType": "source_type", "sourceUrl": "source_url",
            }.items()
        }
        type(self)._shares[token] = {
            "id": share_id, "kind": "recipe", "recipe": snapshot,
            "recipeId": recipe_id, "createdAt": datetime.now(UTC).isoformat(),
            "expiresAt": expires_at, "revokedAt": None,
        }
        return {"id": share_id, "token": token, "expiresAt": expires_at}

    async def list_recipe_shares(self) -> list[dict[str, Any]]:
        return [
            {key: share[key] for key in ("id", "recipeId", "createdAt", "expiresAt", "revokedAt")}
            | {"title": share["recipe"]["title"]}
            for share in type(self)._shares.values()
        ]

    async def revoke_recipe_share(self, share_id: str) -> bool:
        share = next((s for s in type(self)._shares.values() if s["id"] == share_id), None)
        if not share:
            return False
        share["revokedAt"] = datetime.now(UTC).isoformat()
        return True

    async def copy_shared_recipe(self, token: str) -> str:
        share = self.read_shared_recipe(token)
        if not share:
            raise RepositoryError("Share was not found")
        snapshot = share["recipe"]
        row = await self.save_recipe({
            **snapshot,
            "sourceType": "shared",
            "sourceSnapshot": {"shareId": share["id"]},
        })
        return row["id"]

    @classmethod
    def read_shared_recipe(cls, token: str) -> dict[str, Any] | None:
        share = cls._shares.get(token)
        if not share or share["revokedAt"]:
            return None
        if share["expiresAt"] and datetime.fromisoformat(share["expiresAt"].replace("Z", "+00:00")) <= datetime.now(UTC):
            return None
        return deepcopy({key: share[key] for key in ("id", "kind", "recipe", "createdAt")})

    async def get_pantry(self) -> list[dict[str, Any]]:
        return deepcopy(self._pantry)

    async def update_pantry_item(self, item: dict[str, Any]) -> dict[str, Any]:
        row = {"id": item.get("id") or str(uuid4()), **deepcopy(item)}
        row["category"] = row.get("category") or infer_pantry_category(row["name"], row.get("storageLocation", row.get("storage_location", "")))
        if row.get("quantity") is not None and row.get("reference_quantity") is None:
            row["reference_quantity"] = row["quantity"]
        self._pantry = [value for value in self._pantry if value["id"] != row["id"]] + [row]
        return deepcopy(row)

    async def record_pantry_use(
        self, item_id: str, quantity: float, recipe_id: str | None = None,
        meal_title: str | None = None,
    ) -> dict[str, Any]:
        item = next((row for row in self._pantry if row["id"] == item_id), None)
        if not item:
            raise RepositoryError("Pantry item was not found")
        if item.get("quantity") is None:
            raise RepositoryError("Set a remaining quantity before recording use")
        if quantity > float(item["quantity"]):
            raise RepositoryError("Amount used exceeds the remaining quantity")
        recipe = await self.get_recipe(recipe_id) if recipe_id else None
        if recipe_id and not recipe:
            raise RepositoryError("Recipe was not found")
        before = float(item["quantity"])
        item["reference_quantity"] = item.get("reference_quantity") or before
        item["quantity"] = round(before - quantity, 3)
        return {
            "id": str(uuid4()), "itemId": item_id, "name": item["name"],
            "quantityUsed": quantity, "quantityBefore": before,
            "quantityRemaining": item["quantity"], "unit": item.get("unit"),
            "recipeId": recipe_id, "recipeTitle": recipe["title"] if recipe else None,
            "mealTitle": meal_title, "item": deepcopy(item),
        }

    async def save_pantry_photo(
        self, *, image: bytes, width: int, height: int,
        file_id: str, note: str, observations: list[dict[str, Any]],
        apply_to_pantry: bool,
    ) -> dict[str, Any]:
        evidence_id = str(uuid4())
        applied = []
        if apply_to_pantry:
            for observation in observations:
                saved = await self.update_pantry_item({**observation, "provenance": {
                    "sourceType": "pantry_photo", "evidenceId": evidence_id,
                }})
                applied.append(saved["id"])
        row = {
            "id": evidence_id, "created_at": datetime.now(UTC).isoformat(),
            "note": note, "observations": deepcopy(observations),
            "image_bytes": len(image), "image_width": width, "image_height": height,
            "status": "applied" if apply_to_pantry else "captured",
            "applied_item_ids": applied, "image_url": None,
        }
        self._pantry_photos.append(row)
        return deepcopy(row)

    async def get_pantry_photos(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        return deepcopy(self._pantry_photos[::-1][offset:offset + limit])

    async def apply_pantry_photo(
        self, evidence_id: str, observations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        row = next((photo for photo in self._pantry_photos if photo["id"] == evidence_id), None)
        if not row:
            raise RepositoryError("Pantry photo evidence was not found")
        if row["status"] == "applied":
            raise RepositoryError("This pantry photo has already been applied")
        chosen = observations if observations is not None else row["observations"]
        applied = []
        for observation in chosen:
            saved = await self.update_pantry_item({**observation, "provenance": {
                "sourceType": "pantry_photo", "evidenceId": evidence_id,
            }})
            applied.append(saved["id"])
        row.update({"observations": deepcopy(chosen), "applied_item_ids": applied, "status": "applied"})
        return deepcopy(row)

    async def save_meal_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        existing = self._meal_plans.get(plan["weekStart"], {})
        revision_id = plan.get("ruleRevisionId", existing.get("ruleRevisionId"))
        rules = await self.get_meal_plan_rules(revision_id) if revision_id else None
        if revision_id and not rules:
            raise RepositoryError("Meal plan rule revision was not found")
        saved = {**deepcopy(plan), "id": plan.get("id") or existing.get("id") or str(uuid4()),
                 "ruleRevisionId": revision_id, "ruleRevision": rules}
        for entry in saved["entries"]:
            entry["id"] = entry.get("id") or str(uuid4())
        self._meal_plans[saved["weekStart"]] = saved
        return deepcopy(saved)

    async def get_meal_plan(self, week_start: str | None = None) -> dict[str, Any] | None:
        if week_start:
            return deepcopy(self._meal_plans.get(week_start))
        return deepcopy(self._meal_plans[max(self._meal_plans)]) if self._meal_plans else None

    async def get_recent_meal_plans(self, before_week: str, limit: int = 2) -> list[dict[str, Any]]:
        weeks = sorted((week for week in self._meal_plans if week < before_week), reverse=True)[:limit]
        return [deepcopy(self._meal_plans[week]) for week in weeks]

    async def get_meal_plan_rules(self, revision_id: str | None = None) -> dict[str, Any] | None:
        if revision_id:
            return deepcopy(next((item for item in self._rule_revisions if item["id"] == revision_id), None))
        return deepcopy(self._rule_revisions[-1]) if self._rule_revisions else None

    async def get_meal_plan_rule_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return deepcopy(list(reversed(self._rule_revisions))[:limit])

    async def save_meal_plan_rules(self, text: str, expected_revision: int) -> dict[str, Any]:
        current = self._rule_revisions[-1] if self._rule_revisions else None
        if expected_revision != (current["revision"] if current else 0):
            raise RevisionConflictError("Meal plan rules changed. Reload the current rules before saving.")
        if current and current["text"] == text:
            return deepcopy(current)
        saved = {"id": str(uuid4()), "revision": expected_revision + 1, "text": text,
                 "createdAt": datetime.now(UTC).isoformat()}
        self._rule_revisions.append(saved)
        return deepcopy(saved)

    async def save_shopping_list(self, shopping_list: dict[str, Any]) -> dict[str, Any]:
        self._shopping_list = {"id": shopping_list.get("id") or str(uuid4()), **deepcopy(shopping_list)}
        return deepcopy(self._shopping_list)

    async def get_shopping_list(self, list_id: str | None = None) -> dict[str, Any] | None:
        return deepcopy(self._shopping_list)

    async def add_shopping_item(self, item: dict[str, Any], list_id: str | None = None) -> dict[str, Any]:
        if list_id and list_id != self._shopping_list["id"]:
            raise RepositoryError("Shopping list was not found")
        self._shopping_list["items"].append({"id": str(uuid4()), **deepcopy(item), "purchased": False})
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
        if week_start:
            return deepcopy(self._weekly_schedules.get(week_start))
        return deepcopy(self._weekly_schedules[max(self._weekly_schedules)]) if self._weekly_schedules else None

    async def save_weekly_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        value = {
            "id": self._weekly_schedules.get(schedule["weekStart"], {}).get("id") or str(uuid4()),
            "week_start": schedule["weekStart"],
            "days": deepcopy(schedule["days"]),
            "is_normal_week": schedule.get("isNormalWeek", True),
            "remember_rhythm": schedule.get("rememberRhythm", True),
            "notes": schedule.get("notes", self._weekly_schedules.get(schedule["weekStart"], {}).get("notes", "")).strip(),
        }
        self._weekly_schedules[schedule["weekStart"]] = value
        return deepcopy(value)

    async def get_feedback(
        self,
        recipe_id: str | None = None,
        week_start: str | None = None,
        tags: list[str] | None = None,
        feedback_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        items = type(self)._feedback
        if recipe_id:
            items = [
                item
                for item in items
                if (item.get("occurrence") or {}).get("recipe_id") == recipe_id
            ]
        if week_start:
            items = [
                item
                for item in items
                if item.get("week_start") == week_start
                or (item.get("occurrence") or {}).get("week_start") == week_start
            ]
        if tags:
            items = [
                item
                for item in items
                if set(tags).issubset(
                    tag.get("slug") for tag in item.get("tags", []) if isinstance(tag, dict)
                )
            ]
        if feedback_type:
            items = [item for item in items if item.get("feedback_type") == feedback_type]
        return deepcopy(items[: min(max(limit, 1), 100)])

    async def save_feedback(self, feedback: dict[str, Any]) -> dict[str, Any]:
        week_start = feedback.get("weekStart")
        schedule = await self.get_weekly_schedule(week_start) if week_start else None
        occurrence_id = feedback.get("occurrenceId")
        if not occurrence_id and feedback.get("id"):
            existing_feedback = next(
                (item for item in type(self)._feedback if item["id"] == feedback["id"]),
                None,
            )
            occurrence_id = (existing_feedback or {}).get("occurrence_id")
        occurrence = None
        if occurrence_id:
            occurrence = next(
                (item for item in type(self)._occurrences if item["id"] == occurrence_id),
                None,
            )
            if not occurrence:
                raise RepositoryError("Meal occurrence was not found")
        recipe_id = feedback.get("recipeId") or (occurrence or {}).get("recipe_id")
        recipe = await self.get_recipe(recipe_id) if recipe_id else None
        if recipe_id and not recipe:
            raise RepositoryError("Recipe was not found")
        variant = None
        if feedback.get("variantName") and recipe_id:
            variant = next(
                (
                    item
                    for item in type(self)._variants
                    if item["recipe_id"] == recipe_id
                    and item["name"].lower() == feedback["variantName"].lower()
                ),
                None,
            )
            if not variant:
                variant = {
                    "id": str(uuid4()),
                    "recipe_id": recipe_id,
                    "name": feedback["variantName"],
                    "adaptations": deepcopy(feedback.get("adaptations", [])),
                }
                type(self)._variants.append(variant)
            elif feedback.get("adaptations"):
                variant["adaptations"] = deepcopy(feedback["adaptations"])

        if occurrence and variant:
            occurrence.update(
                {
                    "recipe_variant_id": variant["id"],
                    "variation_snapshot": {
                        "name": variant["name"],
                        "adaptations": deepcopy(variant["adaptations"]),
                    },
                    "variant": deepcopy(variant),
                }
            )
        elif not occurrence and recipe_id:
            occurrence = {
                "id": str(uuid4()),
                "meal_plan_entry_id": feedback.get("mealPlanEntryId"),
                "weekly_schedule_id": schedule.get("id") if schedule else None,
                "week_start": week_start,
                "occurred_on": feedback.get("occurredOn"),
                "slot": feedback.get("slot"),
                "title": feedback.get("mealTitle") or (recipe or {}).get("title") or "Meal",
                "recipe_id": recipe_id,
                "recipe_variant_id": variant.get("id") if variant else None,
                "variation_snapshot": {
                    "name": variant["name"],
                    "adaptations": deepcopy(variant["adaptations"]),
                } if variant else {},
                "variant": deepcopy(variant),
            }
            type(self)._occurrences.append(occurrence)

        canonical_tags = []
        for tag_record in feedback.get("tagRecords", []):
            tag = next(
                (
                    item
                    for item in type(self)._feedback_tags
                    if item["slug"] == tag_record["slug"]
                ),
                None,
            )
            if not tag:
                tag = {"id": str(uuid4()), **deepcopy(tag_record)}
                type(self)._feedback_tags.append(tag)
            canonical_tags.append(deepcopy(tag))

        value = {
            "id": feedback.get("id") or str(uuid4()),
            "occurrence_id": occurrence.get("id") if occurrence else None,
            "weekly_schedule_id": schedule.get("id") if schedule else None,
            "week_start": week_start,
            "feedback_type": feedback.get("feedbackType", "change_next_time"),
            "note": feedback["note"],
            "next_time": feedback.get("nextTime", ""),
            "tags": canonical_tags,
            "rating": feedback.get("rating"),
            "created_at": datetime.now(UTC).isoformat(),
            "occurrence": deepcopy(occurrence),
        }
        type(self)._feedback = [
            item for item in type(self)._feedback if item["id"] != value["id"]
        ] + [value]
        type(self)._feedback.sort(key=lambda item: item["created_at"], reverse=True)
        return deepcopy(value)

    async def get_household_memory(
        self,
        include_inactive: bool = False,
        status: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        items = type(self)._memories
        if not include_inactive:
            items = [item for item in items if item.get("active", True)]
        if status:
            items = [item for item in items if item.get("status") == status]
        if scope:
            items = [item for item in items if item.get("scope") == scope]
        return deepcopy(items[: min(max(limit, 1), 100)])

    async def save_household_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        value = {
            "id": memory.get("id") or str(uuid4()), "category": memory.get("category", "planning"),
            "content": memory["content"], "source_type": memory.get("sourceType", "user"),
            "source_detail": memory.get("sourceDetail", "You told us"), "status": memory.get("status", "suggested"),
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


@lru_cache(maxsize=1)
def demo_repository() -> DemoRepository:
    """Keep local demo edits visible across HTTP requests until server restart."""
    return DemoRepository()


def repository_for_request(access_token: str | None = None) -> SupabaseRepository | DemoRepository:
    settings = get_settings()
    if not settings.supabase_configured:
        return demo_repository()
    if access_token:
        return SupabaseRepository(settings, access_token)
    access = get_access_token()
    if not access:
        if settings.auth_required:
            raise RepositoryError("Authentication is required")
        return demo_repository()
    return SupabaseRepository(settings, access.token)
