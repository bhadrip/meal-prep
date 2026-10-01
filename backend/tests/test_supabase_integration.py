"""Roundtrip checks against a disposable local Supabase stack."""

import os
from uuid import uuid4

import httpx
import pytest

from app.application.errors import RepositoryError
from app.application.services import RecipePantryService
from app.config import Settings
from app.infrastructure.repositories import SupabaseRepository


@pytest.mark.asyncio
async def test_local_supabase_week_plan_and_rhythm_roundtrip():
    url = os.environ.get("MEAL_PREP_TEST_SUPABASE_URL")
    anon_key = os.environ.get("MEAL_PREP_TEST_ANON_KEY")
    service_key = os.environ.get("MEAL_PREP_TEST_SERVICE_ROLE_KEY")
    if not all((url, anon_key, service_key)):
        pytest.skip("local Supabase test credentials are not configured")

    email = f"meal-prep-plan-{uuid4()}@example.test"
    password = str(uuid4())
    admin_headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    async with httpx.AsyncClient(base_url=url, timeout=20) as client:
        created = await client.post("/auth/v1/admin/users", headers=admin_headers, json={
            "email": email, "password": password, "email_confirm": True,
        })
        assert created.status_code in (200, 201), created.text
        user_id = created.json()["id"]
        household_id = None
        extra_household_id = None
        try:
            signed_in = await client.post(
                "/auth/v1/token", params={"grant_type": "password"},
                headers={"apikey": anon_key}, json={"email": email, "password": password},
            )
            assert signed_in.status_code == 200, signed_in.text
            repository = SupabaseRepository(
                Settings(supabase_url=url, supabase_anon_key=anon_key, auth_required=True),
                signed_in.json()["access_token"],
            )
            household_id = (await repository.get_household_context())["householdId"]

            saved_recipe = await repository.save_recipe({"title": "Ginger rasam", "tags": ["sickness-friendly", "rasam"]})
            assert saved_recipe["tags"] == ["sickness-friendly", "rasam"]
            await repository.request("POST", "recipes", json=[
                {"id": str(uuid4()), "household_id": household_id, "title": f"Filler recipe {index}"}
                for index in range(26)
            ])
            assert saved_recipe["id"] not in [item["id"] for item in await repository.search_recipes(limit=25)]
            assert [item["id"] for item in await repository.search_recipes(tag="sickness-friendly")] == [saved_recipe["id"]]
            assert [item["id"] for item in await repository.search_recipes(query="rasam")] == [saved_recipe["id"]]
            assert [item["id"] for item in await repository.search_recipes(query="sick")] == [saved_recipe["id"]]
            assert {item["tag"] for item in await repository.list_recipe_tags()} == {"sickness-friendly", "rasam"}
            assert await repository.search_recipes(tag="guest-friendly") == []
            assert await repository.search_recipes(query="not-a-real-tag") == []

            food = RecipePantryService(repository)
            base = saved_recipe["id"]
            variation = (await food.save_recipe({"title": "Pepper rasam"}))["id"]
            graph = await food.get_recipe_graph()
            assert len([n for n in graph["nodes"] if n["kind"] == "recipe"]) == 28
            cuisine = await food.save_recipe_relationship({"sourceRecipeId": base, "type": "cuisine", "label": "South Indian"})
            tag = await food.save_recipe_relationship({"sourceRecipeId": variation, "type": "tag", "label": "protein rich"})
            assert (await repository.search_recipes(tag="protein rich"))[0]["id"] == variation
            variant = await food.save_recipe_relationship({"sourceRecipeId": variation, "targetRecipeId": base, "type": "variant_of"})
            for kind, value in [("goal", "comfort food"), ("meal", "dinner"), ("diet", "vegan")]:
                detail = await food.save_recipe_relationship({"sourceRecipeId": base, "type": kind, "label": value})
                result = await food.browse_recipe_library(filters={"cuisine": ["south indian"], kind: [value]})
                assert result["count"] == 1 and result["items"][0]["id"] == base
                assert result["items"][0]["variationCount"] == 1
                with pytest.raises(RepositoryError, match="already exists"):
                    await repository.save_recipe_relationship({**detail, "id": None})
            await food.save_recipe({"id": base, "title": "Ginger rasam", "totalMinutes": 20,
                                    "meal_types": ["dinner", "lunch"], "tags": ["rasam"]})
            timed = await food.browse_recipe_library(filters={"goal": ["comfort food"], "meal": ["lunch"]}, max_minutes=20)
            assert timed["items"][0]["total_minutes"] == 20
            assert (await food.browse_recipe_library(max_minutes=10))["count"] == 0
            assert (await food.browse_recipe_library(limit=25, offset=25))["count"] == 28
            before = await food.get_recipe_graph()
            # Exercise database validation directly, bypassing service checks.
            for payload, message in [
                ({"sourceRecipeId": base, "targetRecipeId": variation, "type": "variant_of"}, "loop"),
                ({"id": variant["id"], "sourceRecipeId": base, "targetRecipeId": base, "type": "variant_of"}, "different recipes"),
                ({"id": cuisine["id"], "sourceRecipeId": variation, "type": "tag", "label": "protein rich"}, "already exists"),
                ({"sourceRecipeId": base, "type": "cuisine", "label": 42}, "must be text"),
                ({"id": detail["id"], "sourceRecipeId": base, "type": "meal", "label": "dinner"}, "already exists"),
            ]:
                with pytest.raises(RepositoryError, match=message):
                    await repository.save_recipe_relationship(payload)
                assert await food.get_recipe_graph() == before
            await food.save_recipe({"id": base, "title": "Edited rasam", "tags": ["rasam"]})
            assert (await repository.get_recipe(base))["cuisines"] == ["south indian"]
            assert (await repository.get_recipe(base))["meal_types"] == ["dinner", "lunch"]
            await repository.create_household("Other graph kitchen")
            extra_household_id = (await repository.get_household_context())["householdId"]
            foreign = (await repository.save_recipe({"title": "Private soup"}))["id"]
            assert not any(n.get("recipeId") == base for n in (await food.get_recipe_graph())["nodes"])
            assert (await food.browse_recipe_library(filters={"meal": ["dinner"]}))["count"] == 0
            await repository.switch_household(household_id)
            with pytest.raises(RepositoryError, match="Target recipe was not found"):
                await repository.save_recipe_relationship({"sourceRecipeId": base, "targetRecipeId": foreign, "type": "pairs_with"})
            assert not any(n.get("recipeId") == foreign for n in (await food.get_recipe_graph())["nodes"])
            await food.delete_recipe_relationship(tag["id"])
            assert await repository.search_recipes(tag="protein rich") == []
            await food.archive_recipe(variation)
            assert not any(e["id"] == variant["id"] for e in (await food.get_recipe_graph())["edges"])

            first_week = "2030-02-04"
            second_week = "2030-02-11"
            first = await repository.save_meal_plan({
                "weekStart": first_week, "status": "draft",
                "entries": [{"date": first_week, "slot": "dinner", "meal": "Lentil bowls"}],
            })
            assert first["entries"][0]["meal"] == "Lentil bowls"
            second = await repository.save_meal_plan({
                "weekStart": second_week, "status": "draft",
                "entries": [{"date": second_week, "slot": "breakfast", "meal": "Oatmeal"}],
            })
            assert second["entries"][0]["meal"] == "Oatmeal"
            assert (await repository.get_meal_plan(first_week))["id"] == first["id"]
            assert (await repository.get_meal_plan(second_week))["id"] == second["id"]

            edited = await repository.save_meal_plan({
                "id": second["id"], "weekStart": second_week, "status": "draft",
                "entries": [{"date": second_week, "slot": "breakfast", "meal": "Yogurt bowls"}],
            })
            assert edited["entries"][0]["meal"] == "Yogurt bowls"
            assert (await repository.get_meal_plan(first_week))["entries"][0]["meal"] == "Lentil bowls"

            days = [{"day": day, "mode": "quick"} for day in (
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
            )]
            assert (await repository.save_weekly_schedule({"weekStart": second_week, "days": days}))["days"] == days
            days[0]["mode"] = "busy"
            assert (await repository.save_weekly_schedule({"weekStart": second_week, "days": days}))["days"][0]["mode"] == "busy"
        finally:
            if extra_household_id:
                removed = await client.delete("/rest/v1/households", params={"id": f"eq.{extra_household_id}"}, headers=admin_headers)
                assert removed.status_code in (200, 204), removed.text
            if household_id:
                removed = await client.delete(
                    "/rest/v1/households", params={"id": f"eq.{household_id}"},
                    headers={**admin_headers, "Prefer": "return=representation"},
                )
                assert removed.status_code in (200, 204), removed.text
            deleted = await client.delete(f"/auth/v1/admin/users/{user_id}", headers=admin_headers)
            assert deleted.status_code in (200, 204), deleted.text


@pytest.mark.asyncio
async def test_local_notification_inbox_respects_recipient_and_membership():
    url = os.environ.get("MEAL_PREP_TEST_SUPABASE_URL")
    anon_key = os.environ.get("MEAL_PREP_TEST_ANON_KEY")
    service_key = os.environ.get("MEAL_PREP_TEST_SERVICE_ROLE_KEY")
    if not all((url, anon_key, service_key)):
        pytest.skip("local Supabase test credentials are not configured")

    admin_headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    users = []
    household_id = None
    async with httpx.AsyncClient(base_url=url, timeout=20) as client:
        try:
            repositories = []
            emails = []
            for _ in range(2):
                email = f"meal-prep-inbox-{uuid4()}@example.test"
                password = str(uuid4())
                created = await client.post("/auth/v1/admin/users", headers=admin_headers, json={
                    "email": email, "password": password, "email_confirm": True,
                })
                assert created.status_code in (200, 201), created.text
                users.append(created.json()["id"])
                signed_in = await client.post(
                    "/auth/v1/token", params={"grant_type": "password"},
                    headers={"apikey": anon_key}, json={"email": email, "password": password},
                )
                assert signed_in.status_code == 200, signed_in.text
                repositories.append(SupabaseRepository(
                    Settings(supabase_url=url, supabase_anon_key=anon_key, auth_required=True),
                    signed_in.json()["access_token"],
                ))
                emails.append(email)
            owner, invitee = repositories
            household_id = (await owner.get_household_context())["householdId"]

            invitation = await owner.rpc("create_household_invitation", {"invitee_email": emails[1]})
            inbox = await invitee.request("GET", "notifications")
            assert len(inbox) == 1 and inbox[0]["kind"] == "invitation"
            assert await owner.request("PATCH", "notifications",
                params={"id": f"eq.{inbox[0]['id']}"}, json={"read_at": "2026-09-30T12:00:00Z"}) == []

            await invitee.rpc("accept_household_invitation", {"invitation_id": invitation["id"]})
            await owner.save_recipe({"title": "Shared soup", "servings": 4})
            member_inbox = await invitee.request("GET", "notifications")
            assert any(item["title"] == "Joined household" and item["read_at"] for item in member_inbox)
            assert any(item["kind"] == "recipes" for item in member_inbox)
            assert any(item["kind"] == "membership" for item in await owner.request("GET", "notifications"))

            await owner.rpc("remove_household_member", {"member_id": users[1]})
            former_member_inbox = await invitee.request("GET", "notifications")
            assert not any(item["kind"] == "recipes" for item in former_member_inbox)
            assert any(item["kind"] == "access_removed" for item in former_member_inbox)

            bulk = await client.post("/rest/v1/notifications", headers={
                **admin_headers, "Prefer": "return=minimal",
            }, json=[{
                "recipient_id": users[1], "kind": "test", "title": "Test activity",
                "target_path": "/app?view=overview", "event_key": f"test:{uuid4()}",
            } for _ in range(205)])
            assert bulk.status_code in (200, 201), bulk.text
            assert len(await invitee.request("GET", "notifications")) == 200
        finally:
            if household_id:
                removed = await client.delete(
                    "/rest/v1/households", params={"id": f"eq.{household_id}"},
                    headers={**admin_headers, "Prefer": "return=representation"},
                )
                assert removed.status_code in (200, 204), removed.text
            for user_id in users:
                deleted = await client.delete(f"/auth/v1/admin/users/{user_id}", headers=admin_headers)
                assert deleted.status_code in (200, 204), deleted.text
