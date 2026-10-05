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
from ..application.recipe_graph import CATEGORY_FIELDS, category_id, relationships_from_data
from ..config import Settings, get_settings
from .chat import SupabaseChat, DemoChat


PLANNING_TABLES = {
    "weekly_schedules": "weekly schedules",
    "feedback_entries": "feedback",
    "household_memories": "household preferences",
    "meal_plan_rule_revisions": "meal plan rules",
}
PLANNING_FUNCTIONS = {
    "rpc/get_recipe_graph_data": "recipe relationships",
    "rpc/save_recipe_relationship": "recipe relationships",
    "rpc/delete_recipe_relationship": "recipe relationships",
    "rpc/get_experience_feedback": "feedback",
    "rpc/save_experience_feedback": "feedback",
    "rpc/record_pantry_use": "pantry use",
    "rpc/save_meal_plan_rules": "meal plan rules",
    "rpc/get_recent_meal_plans": "planning history",
    "rpc/complete_plan_item": "plan activity",
    "rpc/receive_shopping_item": "shopping receipts",
    "rpc/search_meals": "meal library",
    "rpc/get_meal": "meal library",
    "rpc/save_meal": "meal library",
    "rpc/archive_meal": "meal library",
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


class SupabaseRepository(SupabaseChat):
    async def direct_shares(self, limit=51, offset=0):
        return await self.rpc("list_direct_shares", {"result_limit": limit, "result_offset": offset})

    async def direct_share(self, email, kind, recipe_id=None, week_start=None, meal_id=None):
        return await self.rpc("share_direct", {"requested_email": email, "requested_kind": kind,
                                               "requested_recipe_id": recipe_id, "requested_week_start": week_start,
                                               "requested_meal_id": meal_id})

    async def circle_list(self):
        return await self.rpc("list_my_circles")

    async def circle_create(self, name):
        return await self.rpc("create_circle", {"requested_name": name})

    async def circle_invite(self, circle_id, email):
        return await self.rpc("invite_circle_friend", {"requested_circle_id": circle_id, "requested_email": email})

    async def circle_respond(self, circle_id, accept):
        return await self.rpc("respond_circle_invitation", {"requested_circle_id": circle_id, "requested_accept": accept})

    async def circle_remove_friend(self, circle_id, user_id):
        return await self.rpc("remove_circle_member", {"requested_circle_id": circle_id, "requested_user_id": user_id})

    async def circle_leave(self, circle_id):
        return await self.rpc("leave_circle", {"requested_circle_id": circle_id})

    async def circle_feed(self, limit=51, offset=0, kind=None, circle_id=None):
        return await self.rpc("list_shared_with_me", {"result_limit": limit, "result_offset": offset,
                                                       "requested_kind": kind, "requested_circle_id": circle_id})

    async def circle_get_post(self, share_id):
        return await self.rpc("get_circle_share", {"requested_share_id": share_id})

    async def circle_share_week(self, circle_id, week_start, expected_audience=None):
        if expected_audience is not None:
            return await self.rpc("share_week_with_audience", {"requested_circle_id": circle_id,
                "requested_week_start": week_start, "requested_audience": expected_audience})
        return await self.rpc("share_week_to_circle", {"requested_circle_id": circle_id, "requested_week_start": week_start})

    async def circle_share_recipe(self, circle_id, recipe_id):
        return await self.rpc("share_recipe_to_circle", {"requested_circle_id": circle_id, "requested_recipe_id": recipe_id})

    async def circle_mention_candidates(self, circle_id):
        return await self.rpc("circle_mention_candidates", {"requested_circle_id": circle_id})

    async def circle_send_message(self, circle_id, body, attachment_kind=None, attachment_id=None,
                                  mention_ids=None, expected_audience=None):
        return await self.rpc("send_circle_message", {"requested_circle_id": circle_id, "requested_body": body,
            "requested_attachment_kind": attachment_kind, "requested_attachment_id": attachment_id,
            "requested_mention_ids": mention_ids or [], "requested_audience": expected_audience})

    async def circle_comment(self, share_id, body, target_type, target_id, mention_ids=None):
        return await self.rpc("comment_on_circle_share", {"requested_share_id": share_id, "requested_body": body,
                                                          "requested_target_type": target_type, "requested_target_id": target_id,
                                                          "requested_mention_ids": mention_ids or []})

    async def circle_delete_comment(self, comment_id):
        return await self.rpc("delete_circle_comment", {"requested_comment_id": comment_id})

    async def circle_save_recipe(self, share_id, recipe_id):
        return await self.rpc("save_circle_recipe", {"requested_share_id": share_id, "requested_recipe_id": recipe_id})

    async def circle_revoke_post(self, share_id):
        return await self.rpc("revoke_circle_share", {"requested_share_id": share_id})

    async def search_meals(self, query, limit, offset):
        await self.household_id()
        return await self.rpc("search_meals", {"search_text": query, "result_limit": limit, "result_offset": offset})

    async def get_meal(self, meal_id):
        await self.household_id()
        return await self.rpc("get_meal", {"requested_meal_id": meal_id})

    async def save_meal(self, meal):
        await self.household_id()
        return await self.rpc("save_meal", {"meal": meal})

    async def archive_meal(self, meal_id):
        await self.household_id()
        return await self.rpc("archive_meal", {"requested_meal_id": meal_id})

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

    async def get_recipe_graph_data(self) -> dict[str, Any]:
        return await self.rpc("get_recipe_graph_data")

    async def save_recipe_relationship(self, relationship: dict[str, Any]) -> dict[str, Any]:
        return await self.rpc("save_recipe_relationship", {"requested_relationship": relationship})

    async def delete_recipe_relationship(self, relationship_id: str) -> bool:
        return await self.rpc("delete_recipe_relationship", {"requested_id": relationship_id})

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
            "kind": recipe.get("kind", "recipe"),
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
        if "nutrition" in recipe:
            row["nutrition"] = deepcopy(recipe["nutrition"])
        row.update({field: recipe[field] for field in CATEGORY_FIELDS.values() if field != "tags" and field in recipe})
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

    async def create_meal_share(self, meal_id: str, expires_at: str | None = None) -> dict[str, Any]:
        return await self.rpc("create_meal_share", {"requested_meal_id": meal_id,
                                                     "requested_expires_at": expires_at})

    async def list_public_shares(self) -> list[dict[str, Any]]:
        return await self.rpc("list_public_shares") or []

    async def revoke_public_share(self, share_id: str) -> bool:
        return bool(await self.rpc("revoke_public_share", {"requested_share_id": share_id}))

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
            "acquired_at": item.get("acquiredAt"),
            "freshness_basis": item.get("freshnessBasis"),
            "provenance": item.get("provenance", {}),
        }
        if item.get("reference_quantity") is not None:
            row["reference_quantity"] = item["reference_quantity"]
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

    async def complete_plan_item(self, week_start: str, kind: str, item_id: str, inputs: list[dict], outputs: list[dict]) -> dict:
        return await self.rpc("complete_plan_item", {"requested_week": week_start, "item_kind": kind,
                                                   "item_id": item_id, "used_inputs": inputs, "made_outputs": outputs})

    async def receive_shopping_item(self, item_id: str, quantity: float, unit: str, storage_location: str) -> dict:
        return await self.rpc("receive_shopping_item", {"shopping_item_id": item_id,
                                                       "received_quantity": quantity, "received_unit": unit,
                                                       "received_location": storage_location})

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


class DemoRepository(DemoChat):
    """Deterministic local state used when Supabase is not configured."""

    user_id = "demo"

    def as_user(self, user_id: str):
        from copy import copy
        other = copy(self)
        other.user_id = user_id
        other._recipes = deepcopy(self._recipes)
        return other

    async def circle_list(self):
        return deepcopy([{"id": row["id"], "name": row["name"], "ownerId": row["ownerId"],
                          "members": [{"userId": user, "email": user, "status": status} for user, status in row["members"].items()] if row["ownerId"] == self.user_id else [],
                          "audience": [{"userId": user, "membershipId": row["memberEpochs"][user],
                                        "name": self._chat_name(user)} for user, status in row["members"].items()
                                       if status == "accepted"] if row["members"].get(self.user_id) == "accepted" else [],
                          "memberNames": [user.split('@')[0] for user, status in row["members"].items() if status == "accepted"] if row["members"].get(self.user_id) == "accepted" else [],
                          "memberCount": sum(status == "accepted" for status in row["members"].values()) if row["members"].get(self.user_id) == "accepted" else 0,
                          "myStatus": row["members"].get(self.user_id)}
                         for row in self._circles.values() if self.user_id in row["members"] and row.get("roomType", "group") == "group"])

    async def circle_create(self, name):
        if sum(row["ownerId"] == self.user_id for row in self._circles.values()) >= 30:
            raise RepositoryError("Circle limit reached")
        row = {"id": str(uuid4()), "name": name, "ownerId": self.user_id, "members": {self.user_id: "accepted"},
               "memberEpochs": {self.user_id: str(uuid4())}}
        self._circles[row["id"]] = row
        return deepcopy(row)

    async def circle_invite(self, circle_id, email):
        circle = self._circles.get(circle_id)
        if not circle or circle["ownerId"] != self.user_id or circle.get("roomType") == "direct":
            raise RepositoryError("Circle invitation is not available")
        if email in circle["members"]:
            raise RepositoryError("Friend is already invited or a member")
        if len(circle["members"]) >= 25:
            raise RepositoryError("Circle member limit reached")
        circle["members"][email] = "pending"
        circle["memberEpochs"][email] = str(uuid4())
        return {"circleId": circle_id, "email": email, "status": "pending"}

    async def circle_respond(self, circle_id, accept):
        circle = self._circles.get(circle_id)
        if not circle or circle["members"].get(self.user_id) != "pending":
            raise RepositoryError("Circle invitation was not found")
        if accept:
            circle["members"][self.user_id] = "accepted"
        else:
            del circle["members"][self.user_id]
            del circle["memberEpochs"][self.user_id]
        return {"circleId": circle_id, "accepted": accept}

    async def circle_remove_friend(self, circle_id, user_id):
        circle = self._circles.get(circle_id)
        if not circle or circle["ownerId"] != self.user_id or user_id == self.user_id or user_id not in circle["members"]:
            raise RepositoryError("Circle member was not found")
        del circle["members"][user_id]
        del circle["memberEpochs"][user_id]
        return {"removed": True}

    async def circle_leave(self, circle_id):
        circle = self._circles.get(circle_id)
        if not circle or circle["ownerId"] == self.user_id or circle["members"].get(self.user_id) != "accepted":
            raise RepositoryError("Circle is not available to leave")
        del circle["members"][self.user_id]
        del circle["memberEpochs"][self.user_id]
        return {"left": True}

    def _circle_access(self, circle_id):
        circle = self._circles.get(circle_id)
        if not circle or circle["members"].get(self.user_id) != "accepted":
            raise RepositoryError("Circle is not available")
        return circle

    @staticmethod
    def _circle_audience_keys(circle):
        return sorted(f'{user}:{circle["memberEpochs"][user]}' for user, status in circle["members"].items()
                      if status == "accepted")

    async def circle_feed(self, limit=51, offset=0, kind=None, circle_id=None):
        rows = [self._chat_enrich(self._circle_summary(row)) for row in reversed(list(self._circle_posts.values()))
                if row["revokedAt"] is None and self._circles[row["circleId"]]["members"].get(self.user_id) == "accepted"
                and row["recipientIds"].get(self.user_id) == self._circles[row["circleId"]]["memberEpochs"].get(self.user_id)
                and (kind is None or row["kind"] == kind)
                and (circle_id is None or row["circleId"] == circle_id)]
        return deepcopy(rows[offset:offset + limit])

    def _circle_summary(self, row):
        return {**{key: deepcopy(row[key]) for key in ("id", "circleId", "circleName", "kind", "createdBy", "createdByName", "createdAt", "snapshot")},
                "roomType": self._circles[row["circleId"]].get("roomType", "group"),
                "directPeerName": next((user.split('@')[0] for user in self._circles[row["circleId"]]["members"] if user != self.user_id), None),
                "commentCount": len([comment for comment in self._circle_comments.get(row["id"], []) if not comment.get("deletedAt")])}

    async def circle_mention_candidates(self, circle_id):
        circle = self._circle_access(circle_id)
        return [{"id": user, "name": self._chat_name(user)} for user, status in circle["members"].items() if status == "accepted"]

    async def direct_shares(self, limit=51, offset=0):
        rows = await self.circle_feed(100000, 0)
        return [row for row in rows if row["roomType"] == "direct"][offset:offset + limit]

    async def direct_share(self, email, kind, recipe_id=None, week_start=None, meal_id=None):
        if email == self.user_id:
            raise RepositoryError("Existing friend account was not found")
        now = datetime.now(UTC)
        recent = [row for row in self._circle_posts.values() if row["createdBy"] == self.user_id
                  and self._circles[row["circleId"]].get("roomType") == "direct"
                  and datetime.fromisoformat(row["createdAt"]) > now - timedelta(days=1)]
        if len(recent) >= 20:
            raise RepositoryError("Daily share limit reached")
        existing = next((r for r in self._circles.values() if r.get("roomType") == "direct"
                         and set(r["members"]) == {self.user_id, email}
                         and all(v == "accepted" for v in r["members"].values())), None)
        room_id = existing["id"] if existing else str(uuid4())
        if not existing: self._circles[room_id] = {"id": room_id, "name": "Direct share", "ownerId": self.user_id,
                                  "roomType": "direct", "members": {self.user_id: "accepted", email: "accepted"},
                                  "memberEpochs": {self.user_id: str(uuid4()), email: str(uuid4())}}
        try:
            if kind == "recipe":
                return await self.circle_share_recipe(room_id, recipe_id)
            if kind == "week":
                return await self.circle_share_week(room_id, week_start)
            meal = await self.get_meal(meal_id)
            if not meal or meal.get("archivedAt"):
                raise RepositoryError("Meal was not found")
            components = [{key: deepcopy(part.get(key)) for key in ("name", "quantity", "unit", "source", "action", "recipeId")}
                          for part in meal.get("components", [])]
            recipes = [self._circle_recipe_snapshot(recipe) for recipe in self._recipes
                       if recipe["id"] in {part.get("recipeId") for part in components}]
            return await self._circle_post(room_id, "meal", {"meal": {"id": meal["id"], "name": meal["name"],
                "servings": meal["servings"], "notes": meal.get("notes", ""), "components": components}, "recipes": recipes})
        except Exception:
            if not existing: del self._circles[room_id]
            raise

    async def circle_get_post(self, share_id):
        row = self._circle_posts.get(share_id)
        if not row or row["revokedAt"] or self._circles[row["circleId"]]["members"].get(self.user_id) != "accepted" or row["recipientIds"].get(self.user_id) != self._circles[row["circleId"]]["memberEpochs"].get(self.user_id):
            raise RepositoryError("Shared item was not found")
        recipes = row["snapshot"].get("recipes") or [row["snapshot"].get("recipe")]
        return {**self._chat_enrich(self._circle_summary(row)), "comments": deepcopy([comment for comment in self._circle_comments.get(share_id, [])
                                                                   if not comment.get("deletedAt")]),
                "recipientUserIds": [user for user, epoch in row["recipientIds"].items()
                                     if self._circles[row["circleId"]]["members"].get(user) == "accepted"
                                     and self._circles[row["circleId"]]["memberEpochs"].get(user) == epoch],
                "savedRecipeIds": {recipe["id"]: saved["id"] for recipe in recipes if recipe
                                   for saved in self._recipes if saved.get("sourceSnapshot", {}).get("sourceRecipeId") == recipe["id"]}}

    @staticmethod
    def _circle_recipe_snapshot(recipe):
        fields = ("id", "title", "kind", "description", "servings", "active_minutes", "total_minutes",
                  "tags", "cuisines", "eating_goals", "meal_types", "diets", "ingredients", "instructions", "source_url")
        return {key: deepcopy(recipe[key]) for key in fields if key in recipe}

    async def _circle_post(self, circle_id, kind, snapshot):
        circle = self._circle_access(circle_id)
        now = datetime.now(UTC)
        if sum(row["circleId"] == circle_id and row["createdBy"] == self.user_id
               and datetime.fromisoformat(row["createdAt"]) > now - timedelta(days=1)
               for row in self._circle_posts.values()) >= 100:
            raise RepositoryError("Daily share limit reached")
        row = {"id": str(uuid4()), "circleId": circle_id, "circleName": circle["name"], "kind": kind,
               "createdBy": self.user_id, "createdByName": self.user_id.split('@')[0],
               "createdAt": now.isoformat(), "snapshot": deepcopy(snapshot), "revokedAt": None,
               "recipientIds": {user: circle["memberEpochs"][user] for user, status in circle["members"].items() if status == "accepted"}}
        self._circle_posts[row["id"]] = row
        return self._circle_summary(row)

    async def circle_share_week(self, circle_id, week_start, expected_audience=None):
        circle = self._circle_access(circle_id)
        if expected_audience is not None and expected_audience != self._circle_audience_keys(circle):
            raise RepositoryError("Circle audience changed")
        plan = await self.get_meal_plan(week_start)
        if not plan:
            raise RepositoryError("Weekly plan was not found")
        entries = []
        recipe_ids = set()
        task_recipes = {task.get("id"): task.get("recipeId") for task in plan.get("tasks", [])}
        for original in plan.get("entries", []):
            entry = {key: deepcopy(original.get(key)) for key in ("id", "date", "slot", "slotName", "meal", "servings", "notes")}
            entry["components"] = []
            for original_component in original.get("components") or []:
                component = {key: deepcopy(original_component.get(key)) for key in
                             ("name", "quantity", "unit", "source", "action")}
                component["recipeId"] = original_component.get("recipeId") or task_recipes.get(original_component.get("taskId"))
                if component["recipeId"]:
                    recipe_ids.add(component["recipeId"])
                entry["components"].append(component)
            entries.append(entry)
        recipes = [self._circle_recipe_snapshot(recipe) for recipe in self._recipes if recipe["id"] in recipe_ids]
        return await self._circle_post(circle_id, "week", {"weekStart": week_start, "entries": entries, "recipes": recipes})

    async def circle_share_recipe(self, circle_id, recipe_id):
        self._circle_access(circle_id)
        recipe = await self.get_recipe(recipe_id)
        if not recipe:
            raise RepositoryError("Recipe was not found")
        return await self._circle_post(circle_id, "recipe", {"recipe": self._circle_recipe_snapshot(recipe)})

    async def circle_send_message(self, circle_id, body, attachment_kind=None, attachment_id=None,
                                  mention_ids=None, expected_audience=None):
        circle = self._circle_access(circle_id)

        if expected_audience is not None and expected_audience != self._circle_audience_keys(circle):
            raise RepositoryError("Circle audience changed")
        if not set(mention_ids or []).issubset({user for user, status in circle["members"].items() if status == "accepted"}):
            raise RepositoryError("Mentioned friend is not in this circle")
        if attachment_kind == "recipe":
            recipe = await self.get_recipe(attachment_id)
            if not recipe:
                raise RepositoryError("Recipe was not found")
            snapshot = {"recipe": self._circle_recipe_snapshot(recipe), "caption": body}
        elif attachment_kind == "meal":
            meal = await self.get_meal(attachment_id)
            if not meal or meal.get("archivedAt"):
                raise RepositoryError("Meal was not found")
            components = [{key: deepcopy(part.get(key)) for key in ("name", "quantity", "unit", "source", "action", "recipeId")}
                          for part in meal.get("components", [])]
            recipes = [self._circle_recipe_snapshot(recipe) for recipe in self._recipes
                       if recipe["id"] in {part.get("recipeId") for part in components}]
            snapshot = {"meal": {"id": meal["id"], "name": meal["name"], "servings": meal["servings"],
                                  "notes": meal.get("notes", ""), "components": components},
                        "recipes": recipes, "caption": body}
        else:
            snapshot = {"text": body}
        return await self._circle_post(circle_id, attachment_kind or "message", snapshot)

    async def circle_comment(self, share_id, body, target_type, target_id, mention_ids=None):
        row = await self.circle_get_post(share_id)
        self._circle_access(row["circleId"])
        if not set(mention_ids or []).issubset(set(row["recipientUserIds"])):
            raise RepositoryError("Mentioned friend is not in this circle")
        now = datetime.now(UTC)
        if sum(comment["authorId"] == self.user_id and datetime.fromisoformat(comment["createdAt"]) > now - timedelta(hours=1)
               for comment in self._circle_comments.get(share_id, [])) >= 30:
            raise RepositoryError("Comment rate limit reached")
        recipes = row["snapshot"].get("recipes") or [row["snapshot"].get("recipe")]
        valid = (target_type == "post" and not target_id or
                 target_type == "meal" and row["kind"] == "week" and any(entry["id"] == target_id for entry in row["snapshot"]["entries"]) or
                 target_type == "recipe" and any(recipe and recipe["id"] == target_id for recipe in recipes))
        if not valid:
            raise RepositoryError("Comment target was not found")
        comment = {"id": str(uuid4()), "authorId": self.user_id, "authorName": self.user_id.split('@')[0], "body": body, "targetType": target_type,
                   "targetId": target_id, "createdAt": now.isoformat()}
        self._circle_comments.setdefault(share_id, []).append(comment)
        return deepcopy(comment)

    async def circle_delete_comment(self, comment_id):
        for share_id, comments in self._circle_comments.items():
            comment = next((item for item in comments if item["id"] == comment_id), None)
            if comment:
                post = self._circle_posts[share_id]
                owner = self._circles[post["circleId"]]["ownerId"]
                if self.user_id not in (comment["authorId"], post["createdBy"], owner):
                    break
                comment["deletedAt"] = comment.get("deletedAt") or datetime.now(UTC).isoformat()
                return {"removed": True}
        raise RepositoryError("Comment was not found")

    async def circle_save_recipe(self, share_id, recipe_id):
        row = await self.circle_get_post(share_id)
        recipes = row["snapshot"].get("recipes") or [row["snapshot"].get("recipe")]
        recipe = next((item for item in recipes if item and item["id"] == recipe_id), None)
        if not recipe:
            raise RepositoryError("Shared recipe was not found")
        key = (self.user_id, share_id, recipe_id)
        existing = next((item for item in self._recipes if item.get("sourceSnapshot", {}).get("sourceRecipeId") == recipe_id), None)
        if existing:
            self._circle_saves[key] = existing["id"]
            return {"recipeId": existing["id"], "alreadySaved": True}
        saved = await self.save_recipe({**recipe, "id": str(uuid4()), "sourceType": "shared",
                                       "sourceSnapshot": {"circleShareId": share_id, "sourceRecipeId": recipe_id}})
        self._circle_saves[key] = saved["id"]
        return {"recipeId": saved["id"], "alreadySaved": False}

    async def circle_revoke_post(self, share_id):
        row = self._circle_posts.get(share_id)
        if not row or row["createdBy"] != self.user_id:
            raise RepositoryError("Shared item was not found")
        row["revokedAt"] = datetime.now(UTC).isoformat()
        return {"revoked": True}

    async def search_meals(self, query, limit, offset):
        rows = [deepcopy(row) for row in self._meals.values() if not row.get("archivedAt")
                and (not query or query.casefold() in str([row["name"], row["notes"], row["components"]]).casefold())]
        rows.sort(key=lambda row: (row["updatedAt"], row["id"]), reverse=True)
        return {"items": rows[offset:offset + limit], "total": len(rows), "limit": limit, "offset": offset, "query": query}

    async def get_meal(self, meal_id):
        return deepcopy(self._meals.get(meal_id))

    async def save_meal(self, meal):
        old = self._meals.get(meal["id"], {})
        now = datetime.now(UTC).isoformat()
        changed = any(old.get(key) != meal.get(key) for key in ("name", "servings", "notes", "components"))
        saved = {**deepcopy(meal), "revision": old.get("revision", 0) + int(changed), "archivedAt": None,
                 "createdAt": old.get("createdAt", now), "updatedAt": now}
        self._meals[meal["id"]] = saved
        return deepcopy(saved)

    async def archive_meal(self, meal_id):
        row = self._meals[meal_id]
        row["archivedAt"] = row.get("archivedAt") or datetime.now(UTC).isoformat()
        return deepcopy(row)

    def __init__(self) -> None:
        self._circles = {}
        self._circle_posts = {}
        self._circle_comments = {}
        self._circle_saves = {}
        self._chat = {"profiles": {}, "states": {}, "reactions": {}, "sends": {}}
        self._context = deepcopy(self._context)
        self._pantry = deepcopy(self._pantry)
        self._shopping_list = deepcopy(self._shopping_list)
        self._activities = {}
        self._meals = {}
        self._receipts = {}
        self._recipes = deepcopy(self._recipes)
        self._recipe_relationships: list[dict[str, Any]] = []
        initial_plan = deepcopy(self._meal_plan)
        initial_plan["tasks"] = []
        for index, entry in enumerate(initial_plan["entries"]):
            entry["id"] = entry.get("id") or str(uuid4())
            entry["date"] = (date.fromisoformat(initial_plan["weekStart"]) + timedelta(days=index)).isoformat()
            entry["slotName"] = "Dinner"
            entry["notes"] = ""
            entry["components"] = []
            entry["completedAt"] = None
            entry["sourceMeal"] = None
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

    async def get_recipe_graph_data(self) -> dict[str, Any]:
        return {"recipes": deepcopy(sorted(self._recipes, key=lambda r: r["title"].casefold())),
                "relationships": deepcopy(self._recipe_relationships)}

    def _remove_recipe_relationship(self, edge: dict[str, Any]) -> None:
        if edge["type"] in CATEGORY_FIELDS:
            field = CATEGORY_FIELDS[edge["type"]]
            for recipe in self._recipes:
                if recipe["id"] == edge["sourceRecipeId"]:
                    recipe[field] = [value for value in recipe.get(field, []) if value != edge["label"]]
        else:
            self._recipe_relationships = [r for r in self._recipe_relationships if r["id"] != edge["id"]]

    async def save_recipe_relationship(self, relationship: dict[str, Any]) -> dict[str, Any]:
        old = next((r for r in relationships_from_data(await self.get_recipe_graph_data()) if r["id"] == relationship.get("id")), None)
        if old:
            self._remove_recipe_relationship(old)
        saved = deepcopy(relationship)
        if saved["type"] in CATEGORY_FIELDS:
            saved["id"] = category_id(saved["type"], saved["sourceRecipeId"], saved["label"])
            field = CATEGORY_FIELDS[saved["type"]]
            for recipe in self._recipes:
                if recipe["id"] == saved["sourceRecipeId"]:
                    recipe[field] = [*recipe.get(field, []), saved["label"]]
        else:
            saved["id"] = old["id"] if old and old["type"] not in CATEGORY_FIELDS else str(uuid4())
            self._recipe_relationships.append(saved)
        return deepcopy(saved)

    async def delete_recipe_relationship(self, relationship_id: str) -> bool:
        old = next((r for r in relationships_from_data(await self.get_recipe_graph_data()) if r["id"] == relationship_id), None)
        if not old:
            return False
        self._remove_recipe_relationship(old)
        return True

    async def save_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        existing = next((r for r in self._recipes if r["id"] == recipe.get("id")), {})
        row = {"id": recipe.get("id") or str(uuid4()),
               **{field: deepcopy(existing.get(field, [])) for field in CATEGORY_FIELDS.values()},
               **({"nutrition": deepcopy(existing["nutrition"])} if "nutrition" in existing else {}), **deepcopy(recipe)}
        for camel, snake in (("totalMinutes", "total_minutes"), ("activeMinutes", "active_minutes"),
                             ("sourceUrl", "source_url"), ("sourceType", "source_type")):
            if camel in recipe:
                row[snake] = row.pop(camel)
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
        snapshot["kind"] = recipe.get("kind", "recipe")
        type(self)._shares[token] = {
            "id": share_id, "kind": "recipe", "recipe": snapshot,
            "recipeId": recipe_id, "createdAt": datetime.now(UTC).isoformat(),
            "expiresAt": expires_at, "revokedAt": None, "ownerId": self.user_id,
        }
        return {"id": share_id, "token": token, "expiresAt": expires_at}

    async def list_recipe_shares(self) -> list[dict[str, Any]]:
        return [
            {key: share[key] for key in ("id", "recipeId", "createdAt", "expiresAt", "revokedAt")}
            | {"title": share["recipe"]["title"]}
            for share in type(self)._shares.values() if share["kind"] == "recipe" and share.get("ownerId") == self.user_id
        ]

    async def create_meal_share(self, meal_id: str, expires_at: str | None = None) -> dict[str, Any]:
        meal = await self.get_meal(meal_id)
        if not meal or meal.get("archivedAt"):
            raise RepositoryError("Meal was not found")
        token = token_hex(32)
        share_id = str(uuid4())
        components = [{key: deepcopy(part.get(key)) for key in ("name", "quantity", "unit", "source", "action", "recipeId")}
                      for part in meal.get("components", [])]
        recipes = [self._circle_recipe_snapshot(recipe) for recipe in self._recipes
                   if recipe["id"] in {part.get("recipeId") for part in components}]
        type(self)._shares[token] = {"id": share_id, "kind": "meal", "mealId": meal_id,
            "meal": {"name": meal["name"], "servings": meal["servings"], "notes": meal.get("notes", ""),
                     "components": components, "recipes": recipes}, "ownerId": self.user_id,
            "createdAt": datetime.now(UTC).isoformat(), "expiresAt": expires_at, "revokedAt": None}
        return {"id": share_id, "token": token, "expiresAt": expires_at}

    async def list_public_shares(self) -> list[dict[str, Any]]:
        return [{"id": s["id"], "kind": s["kind"], "sourceId": s.get("recipeId") or s.get("mealId"),
                 "title": (s.get("recipe") or s.get("meal"))["title" if s["kind"] == "recipe" else "name"],
                 "createdAt": s["createdAt"], "expiresAt": s["expiresAt"], "revokedAt": s["revokedAt"],
                 "token": None if s["revokedAt"] else token}
                for token, s in type(self)._shares.items() if s.get("ownerId") == self.user_id]

    async def revoke_public_share(self, share_id: str) -> bool:
        share = next((s for s in type(self)._shares.values()
                      if s["id"] == share_id and s.get("ownerId") == self.user_id), None)
        if not share:
            return False
        share["revokedAt"] = datetime.now(UTC).isoformat()
        return True

    async def revoke_recipe_share(self, share_id: str) -> bool:
        return await self.revoke_public_share(share_id)

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
        if not share or share["revokedAt"] or share["kind"] != "recipe":
            return None
        if share["expiresAt"] and datetime.fromisoformat(share["expiresAt"].replace("Z", "+00:00")) <= datetime.now(UTC):
            return None
        return deepcopy({key: share[key] for key in ("id", "kind", "recipe", "createdAt")})

    @classmethod
    def read_shared_food(cls, token: str) -> dict[str, Any] | None:
        share = cls._shares.get(token)
        if not share or share["revokedAt"]:
            return None
        if share["expiresAt"] and datetime.fromisoformat(share["expiresAt"].replace("Z", "+00:00")) <= datetime.now(UTC):
            return None
        return deepcopy({key: share[key] for key in ("id", "kind", "createdAt", share["kind"])})

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

    async def complete_plan_item(self, week_start: str, kind: str, item_id: str, inputs: list[dict], outputs: list[dict]) -> dict:
        if item_id in self._activities:
            return {"plan": await self.get_meal_plan(week_start), "activity": deepcopy(self._activities[item_id])}
        plan = deepcopy(self._meal_plans.get(week_start))
        item = next((row for row in (plan or {}).get("entries" if kind == "meal" else "tasks", []) if row["id"] == item_id), None)
        if not item:
            raise RepositoryError("Plan item was not found")
        pantry = deepcopy(self._pantry)
        for used in inputs:
            stock = next((row for row in pantry if row["id"] == used["itemId"]), None)
            if not stock or stock.get("quantity") is None or stock["quantity"] < used["quantity"]:
                raise RepositoryError("Not enough known pantry quantity")
            stock["quantity"] = round(stock["quantity"] - used["quantity"], 3)
        output_records = []
        for output in outputs:
            stock = {"id": str(uuid4()), **deepcopy(output), "quantityConfidence": "exact",
                     "reference_quantity": output["quantity"],
                     "provenance": {"sourceType": "plan_activity", "planItemId": item_id,
                                    "recipeId": item.get("recipeId")}}
            pantry.append(stock)
            output_records.append({"itemId": stock["id"], **deepcopy(output)})
        completed = datetime.now(UTC).isoformat()
        item["completedAt"] = completed
        if kind == "task":
            item["stockOutputs"] = output_records
        activity = {"itemId": item_id, "kind": kind, "completedAt": completed,
                    "inputs": deepcopy(inputs), "outputs": output_records}
        self._pantry, self._meal_plans[week_start], self._activities[item_id] = pantry, plan, activity
        return {"plan": deepcopy(plan), "activity": deepcopy(activity)}

    async def receive_shopping_item(self, item_id: str, quantity: float, unit: str, storage_location: str) -> dict:
        if item_id in self._receipts:
            return deepcopy(self._receipts[item_id])
        item = next((row for row in self._shopping_list["items"] if row["id"] == item_id), None)
        if not item:
            raise RepositoryError("Shopping item was not found")
        stock = await self.update_pantry_item({"name": item["name"], "quantity": quantity, "unit": unit,
                                               "storageLocation": storage_location, "quantityConfidence": "exact",
                                               "acquiredAt": datetime.now(UTC).date().isoformat(),
                                               "provenance": {"sourceType": "shopping_receipt", "shoppingItemId": item_id}})
        item.update({"purchased": True, "purchasedQuantity": quantity, "receivedPantryItemId": stock["id"]})
        result = {"item": deepcopy(item), "pantryItem": stock}
        self._receipts[item_id] = result
        return deepcopy(result)

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
        values = deepcopy(shopping_list)
        retained = [row for row in self._shopping_list["items"] if row.get("receivedPantryItemId")
                    and row["id"] not in {item.get("id") for item in values["items"]}]
        values["items"].extend(deepcopy(retained))
        for row in values["items"]:
            existing = next((item for item in self._shopping_list["items"] if item["id"] == row.get("id")), {})
            if existing.get("receivedPantryItemId"):
                row.update({"receivedPantryItemId": existing["receivedPantryItemId"], "purchased": True,
                            "purchasedQuantity": existing.get("purchasedQuantity")})
        self._shopping_list = {**values, "id": shopping_list.get("id") or str(uuid4())}
        for item in self._shopping_list["items"]:
            item["id"] = item.get("id") or str(uuid4())
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
