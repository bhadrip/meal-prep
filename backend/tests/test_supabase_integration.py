"""Roundtrip checks against a disposable local Supabase stack."""

import os
import asyncio
from uuid import uuid4

import httpx
import pytest

from app.application.services import RecipePantryService, HouseholdService, PlanningService, ShoppingService
from app.application.circles import CircleService
from app.config import Settings
from app.application.errors import ApplicationError, RepositoryError, RevisionConflictError
from app.infrastructure.repositories import SupabaseRepository


@pytest.mark.asyncio
async def test_local_friend_circle_sharing_and_inbox_isolation():
    url = os.environ.get("MEAL_PREP_TEST_SUPABASE_URL")
    anon = os.environ.get("MEAL_PREP_TEST_ANON_KEY")
    secret = os.environ.get("MEAL_PREP_TEST_SERVICE_ROLE_KEY")
    if not all((url, anon, secret)):
        pytest.skip("local Supabase test credentials are not configured")
    admin = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    users, homes = [], []
    async with httpx.AsyncClient(base_url=url, timeout=20) as client:
        try:
            repos = []
            for role in ("owner", "friend", "outsider"):
                email, password = f"circle-{role}-{uuid4()}@example.test", str(uuid4())
                response = await client.post('/auth/v1/admin/users', headers=admin,
                    json={"email": email, "password": password, "email_confirm": True})
                assert response.status_code in (200, 201), response.text
                users.append(response.json()["id"])
                login = await client.post('/auth/v1/token', params={"grant_type": "password"},
                    headers={"apikey": anon}, json={"email": email, "password": password})
                assert login.status_code == 200, login.text
                repo = SupabaseRepository(Settings(supabase_url=url, supabase_anon_key=anon, auth_required=True), login.json()["access_token"])
                homes.append((await repo.get_household_context())["householdId"])
                repos.append((repo, email))
            (owner, _), (friend, friend_email), (outsider, _) = repos
            own, peer, stranger = CircleService(owner), CircleService(friend), CircleService(outsider)
            circle = await own.create_circle("Dinner friends")
            recipe = await RecipePantryService(owner).save_recipe({"title": "Golden dal", "servings": 4,
                "ingredients": [{"name": "Lentils", "quantity": 200, "unit": "g"}]})
            week = "2030-02-04"
            await PlanningService(owner).save_meal_plan({"weekStart": week, "entries": [{"id": str(uuid4()),
                "date": week, "slot": "dinner", "meal": "Dal bowls", "components": [{"name": "Golden dal",
                "quantity": 4, "unit": "servings", "source": "cook", "recipeId": recipe["id"]}]}]})
            await RecipePantryService(owner).archive_recipe(recipe["id"])
            with pytest.raises(RepositoryError):
                await own.share_recipe(circle["id"], recipe["id"])
            old_share = await own.share_week(circle["id"], week)
            await own.invite_friend(circle["id"], friend_email)
            with pytest.raises(ApplicationError, match="Existing friend account was not found"):
                await own.invite_friend(circle["id"], "missing-circle-account@example.test")
            assert (await peer.list_circles())["items"][0]["myStatus"] == "pending"
            assert (await peer.list_shared_with_me())["items"] == []
            with pytest.raises(RepositoryError):
                await peer.share_recipe(circle["id"], recipe["id"])
            await peer.respond_invitation(circle["id"], True)
            assert (await peer.list_circles())["items"][0]["memberCount"] == 2
            with pytest.raises(RepositoryError):
                await peer.get_shared_item(old_share["id"])
            with pytest.raises(RepositoryError):
                await peer.comment(old_share["id"], "Too old")
            with pytest.raises(RepositoryError):
                await peer.save_shared_recipe(old_share["id"], recipe["id"])
            shared = await own.share_week(circle["id"], week)
            assert (await peer.list_shared_with_me())["items"][0]["id"] == shared["id"]
            message = await own.send_message(circle["id"], "What are you making tonight?")
            assert [item["id"] for item in (await peer.list_shared_with_me(circle_id=circle["id"], kind="message"))["items"]] == [message["id"]]
            assert (await peer.get_shared_item(message["id"]))["snapshot"]["text"] == "What are you making tonight?"
            message_reply = await peer.comment(message["id"], "Dal bowls")
            assert message_reply["body"] == "Dal bowls"
            assert (await own.list_shared_with_me(circle_id=circle["id"], kind="message"))["items"][0]["commentCount"] == 1
            with pytest.raises(RepositoryError):
                await stranger.send_message(circle["id"], "I should not be here")
            with pytest.raises(RepositoryError):
                await stranger.get_shared_item(message["id"])
            assert await friend.request("GET", "notifications", params={"select": "kind", "kind": "eq.circle_message"})
            friend_inbox = await friend.request("GET", "notifications", params={"select": "kind", "kind": "eq.circle_share"})
            assert friend_inbox and friend_inbox[0]["kind"] == "circle_share"
            snap = (await peer.get_shared_item(shared["id"]))["snapshot"]
            assert snap["entries"][0]["meal"] == "Dal bowls"
            assert snap["recipes"][0]["ingredients"][0]["name"] == "Lentils"
            assert "household_id" not in str(snap) and "pantryItemId" not in str(snap)
            with pytest.raises(RepositoryError):
                await stranger.get_shared_item(shared["id"])
            with pytest.raises(RepositoryError):
                await friend.request("PATCH", "circle_posts", params={"id": f"eq.{shared['id']}"},
                    json={"snapshot": {"entries": []}})
            with pytest.raises(RepositoryError):
                await friend.request("GET", "circle_post_recipients", params={"select": "user_id"})
            with pytest.raises(RepositoryError):
                await peer.comment(shared["id"], "Wrong meal", "meal", str(uuid4()))
            first_comment = await peer.comment(shared["id"], "How did you season the dal?", "meal", snap["entries"][0]["id"])
            for index in range(29):
                await peer.comment(shared["id"], f"Follow-up {index}")
            with pytest.raises(ApplicationError, match="Comment rate limit"):
                await peer.comment(shared["id"], "One too many")
            inbox = await owner.request("GET", "notifications", params={"select": "kind,title", "kind": "eq.circle_comment"})
            assert inbox and inbox[0]["kind"] == "circle_comment"
            with pytest.raises(RepositoryError):
                await stranger.delete_comment(first_comment["id"])
            await own.delete_comment(first_comment["id"])
            assert all(item["id"] != first_comment["id"] for item in (await peer.get_shared_item(shared["id"]))["comments"])
            assert await owner.request("GET", "notifications", params={"select": "id", "event_key": f"eq.circle-comment:{first_comment['id']}"}) == []
            with pytest.raises(ApplicationError, match="Comment rate limit"):
                await peer.comment(shared["id"], "Deletion does not reset the limit")
            await peer.delete_comment(first_comment["id"])
            copied = await peer.save_shared_recipe(shared["id"], recipe["id"])
            assert copied["recipeId"] != recipe["id"]
            assert (await peer.save_shared_recipe(shared["id"], recipe["id"]))["alreadySaved"]
            assert (await friend.get_recipe(copied["recipeId"]))["title"] == "Golden dal"
            assert await owner.get_recipe(copied["recipeId"]) is None
            await RecipePantryService(friend).archive_recipe(copied["recipeId"])
            assert (await peer.get_shared_item(shared["id"]))["savedRecipeIds"] == {}
            replacement = await peer.save_shared_recipe(shared["id"], recipe["id"])
            assert replacement["recipeId"] != copied["recipeId"] and not replacement["alreadySaved"]
            another_share = await own.share_week(circle["id"], week)
            assert (await peer.get_shared_item(another_share["id"]))["savedRecipeIds"][recipe["id"]] == replacement["recipeId"]
            assert (await peer.save_shared_recipe(another_share["id"], recipe["id"]))["alreadySaved"]
            await RecipePantryService(friend).archive_recipe(replacement["recipeId"])
            concurrent = await asyncio.gather(peer.save_shared_recipe(shared["id"], recipe["id"]),
                peer.save_shared_recipe(another_share["id"], recipe["id"]))
            assert concurrent[0]["recipeId"] == concurrent[1]["recipeId"]
            assert concurrent[0]["recipeId"] != replacement["recipeId"]
            assert sorted(item["alreadySaved"] for item in concurrent) == [False, True]
            await own.remove_friend(circle["id"], users[1])
            with pytest.raises(RepositoryError):
                await peer.get_shared_item(shared["id"])
            assert await friend.request("GET", "notifications", params={"select": "kind", "kind": "eq.circle_share"}) == []
            assert (await friend.get_recipe(concurrent[0]["recipeId"]))["title"] == "Golden dal"
            await own.invite_friend(circle["id"], friend_email)
            await peer.respond_invitation(circle["id"], True)
            assert await friend.request("GET", "notifications", params={"select": "kind", "kind": "eq.circle_share"}) == []
            with pytest.raises(RepositoryError):
                await peer.get_shared_item(shared["id"])
            fresh = await own.share_week(circle["id"], week)
            assert (await peer.get_shared_item(fresh["id"]))["id"] == fresh["id"]
            await peer.leave_circle(circle["id"])
            with pytest.raises(RepositoryError):
                await peer.get_shared_item(shared["id"])
            await own.revoke_share(shared["id"])
            await own.delete_comment(message_reply["id"])
            assert await owner.request("GET", "notifications", params={"select": "kind", "kind": "eq.circle_comment"}) == []
            with pytest.raises(RepositoryError):
                await peer.get_shared_item(shared["id"])
        finally:
            for home in homes:
                removed = await client.delete('/rest/v1/households', headers=admin, params={"id": f"eq.{home}"})
                assert removed.status_code in (200, 204), removed.text
            for user in users:
                deleted = await client.delete(f'/auth/v1/admin/users/{user}', headers=admin)
                assert deleted.status_code in (200, 204), deleted.text


@pytest.mark.asyncio
async def test_local_supabase_unified_plan_activity_and_household_isolation():
    url = os.environ.get("MEAL_PREP_TEST_SUPABASE_URL")
    anon = os.environ.get("MEAL_PREP_TEST_ANON_KEY")
    secret = os.environ.get("MEAL_PREP_TEST_SERVICE_ROLE_KEY")
    if not all((url, anon, secret)):
        pytest.skip("local Supabase test credentials are not configured")
    admin = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    email, password = f"meal-plan-components-{uuid4()}@example.test", str(uuid4())
    households = []
    async with httpx.AsyncClient(base_url=url, timeout=20) as client:
        created = await client.post('/auth/v1/admin/users', headers=admin,
                                    json={"email": email, "password": password, "email_confirm": True})
        assert created.status_code in (200, 201), created.text
        user_id = created.json()["id"]
        try:
            login = await client.post('/auth/v1/token', params={"grant_type": "password"}, headers={"apikey": anon},
                                      json={"email": email, "password": password})
            assert login.status_code == 200
            repo = SupabaseRepository(Settings(supabase_url=url, supabase_anon_key=anon, auth_required=True), login.json()["access_token"])
            home = (await repo.get_household_context())["householdId"]
            households.append(home)
            household, food, planning, shopping = HouseholdService(repo), RecipePantryService(repo), PlanningService(repo), ShoppingService(repo)
            slots = (await household.get_context())["mealSlots"]
            await household.configure_meal_slots([{"id": "kids-am", "name": "Kids snack AM", "enabled": True}, *slots])
            recipe = await food.save_recipe({"title": "Dal", "servings": 4, "ingredients": [{"name": "Lentils", "quantity": 200, "unit": "g"}]})
            lentils = await food.update_pantry_item({"name": "Lentils", "quantity": 500, "unit": "g", "quantityConfidence": "exact"})
            task_id, meal_id, week = str(uuid4()), str(uuid4()), "2030-02-04"
            plan = await planning.save_meal_plan({"weekStart": week, "entries": [{"id": meal_id, "date": week, "slot": "kids-am", "meal": "Dal bowl",
                "components": [{"name": "Dal", "quantity": 4, "unit": "servings", "source": "task", "taskId": task_id}]}],
                "tasks": [{"id": task_id, "date": "2030-02-03", "title": "Cook dal", "recipeId": recipe["id"], "servings": 8}]})
            assert plan["entries"][0]["id"] == meal_id
            guide = {"basis": "Ingredient estimate", "profiles": [{"name": "Adults", "serving": "More dal, less rice", "portion": "1 bowl", "valueType": "estimated",
                "amounts": {"protein": 25, "calories": 450}, "macros": {"protein": "high"}, "micronutrients": [{"nutrient": "Iron", "source": "Lentils"}]}]}
            plan = await planning.update_plan_item(week, "meal", {"id": meal_id, "nutrition": guide})
            nutrition = plan["entries"][0]["nutrition"]
            with_recipe_nutrition = await food.save_recipe({**recipe, "nutrition": guide})
            assert with_recipe_nutrition["nutrition"] == nutrition
            retained = await food.save_recipe(recipe)
            assert retained["nutrition"] == nutrition
            with pytest.raises(ApplicationError):
                await food.save_recipe({**recipe, "nutrition": {"basis": "Estimate", "profiles": []}})
            assert (await food.get_recipe(recipe["id"]))["nutrition"] == nutrition
            assert nutrition["profiles"][0]["macros"]["fat"] == "unknown"
            assert (await planning.get_meal_plan(week))["entries"][0]["nutrition"] == nutrition
            with pytest.raises(ApplicationError):
                await planning.update_plan_item(week, "meal", {"id": meal_id, "nutrition": {"basis": "Estimate", "profiles": []}})
            assert await planning.get_meal_plan(week) == plan
            assert plan["tasks"][0]["recipeSnapshot"]["ingredients"][0]["quantity"] == 200
            # Save keeps the entry row: existing occurrence/feedback references survive edits.
            occurrence = await repo.request('POST', 'meal_occurrences', json={"household_id": home, "meal_plan_entry_id": meal_id, "title": "Dal bowl"})
            await planning.update_plan_item(week, "meal", {"id": meal_id, "notes": "Serve warm"})
            assert (await repo.request('GET', 'meal_occurrences', params={"id": f"eq.{occurrence[0]['id']}"}))[0]["meal_plan_entry_id"] == meal_id
            # All stock changes roll back when an output fails after an input is applied.
            with pytest.raises(RepositoryError):
                await repo.complete_plan_item(week, "task", task_id, [{"itemId": lentils["id"], "quantity": 400}],
                                               [{"name": "Dal", "quantity": -1, "unit": "servings"}])
            assert (await repo.get_pantry())[0]["quantity"] == 500
            cooked, retry = await asyncio.gather(*[repo.complete_plan_item(week, "task", task_id,
                [{"itemId": lentils["id"], "quantity": 400}], [{"name": "Dal", "quantity": 7, "unit": "servings"}]) for _ in range(2)])
            assert cooked["activity"] == retry["activity"]
            pantry = await repo.get_pantry()
            assert next(row["quantity"] for row in pantry if row["id"] == lentils["id"]) == 100
            assert len([row for row in pantry if row["name"] == "Dal"]) == 1
            dal_id = cooked["activity"]["outputs"][0]["itemId"]
            eaten = await planning.complete_item(week, "meal", meal_id, [{"itemId": dal_id, "quantity": 4}])
            assert eaten["plan"]["entries"][0]["completedAt"]
            assert eaten["plan"]["entries"][0]["nutrition"] == nutrition
            with pytest.raises(RepositoryError, match="Completed"):
                await repo.save_meal_plan({**eaten["plan"], "entries": [{**eaten["plan"]["entries"][0], "nutrition": None}]})
            assert next(row["quantity"] for row in await repo.get_pantry() if row["id"] == dal_id) == 3
            await planning.update_plan_item(week, "task", {"title": "Pack snacks"})
            line = (await shopping.add_item({"name": "Rotis", "quantity": 1, "unit": "pack"}))["items"][0]
            received, retry = await asyncio.gather(*[shopping.receive_item(line["id"], 20, "pieces") for _ in range(2)])
            assert received["pantryItem"]["id"] == retry["pantryItem"]["id"]
            assert len([row for row in await repo.get_pantry() if row["name"] == "Rotis"]) == 1
            # A later list save keeps the receipt identity and cannot duplicate pantry stock.
            saved_list = await repo.get_shopping_list()
            await shopping.save(saved_list)
            assert (await shopping.receive_item(line["id"], 20, "pieces"))["pantryItem"]["id"] == received["pantryItem"]["id"]
            await repo.create_household("Other household")
            other = (await repo.get_household_context())["householdId"]
            households.append(other)
            foreign_stock = await food.update_pantry_item({"name": "Private rotis", "quantity": 20, "unit": "pieces"})
            foreign_recipe = await food.save_recipe({"title": "Private recipe"})
            await repo.switch_household(home)
            standalone = (await planning.update_plan_item(week, "task", {"title": "Unfinished task"}))["tasks"][-1]
            with pytest.raises(RepositoryError, match="not found"):
                await repo.complete_plan_item(week, "task", standalone["id"], [{"itemId": foreign_stock["id"], "quantity": 1}], [])
            with pytest.raises(RepositoryError, match="household"):
                await repo.save_meal_plan({**await repo.get_meal_plan(week), "tasks": [
                    * (await repo.get_meal_plan(week))["tasks"], {"id": str(uuid4()), "title": "Foreign cooking", "recipeId": foreign_recipe["id"]}]})
            assert not (await repo.get_meal_plan(week))["tasks"][-1]["completedAt"]
        finally:
            for household_id in households:
                removed = await client.delete('/rest/v1/households', headers=admin, params={"id": f"eq.{household_id}"})
                assert removed.status_code in (200, 204), removed.text
            deleted = await client.delete(f'/auth/v1/admin/users/{user_id}', headers=admin)
            assert deleted.status_code in (200, 204), deleted.text


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
        second_household_id = None
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
            assert await repository.get_meal_plan_rules() is None
            first_rules = await repository.save_meal_plan_rules("Saturday pasta; reuse it Monday.", 0)
            second_rules = await repository.save_meal_plan_rules("Saturday stir-fry.", 1)
            assert (await repository.get_meal_plan_rules(first_rules["id"]))["text"] == first_rules["text"]
            assert await repository.get_meal_plan_rule_history() == [second_rules, first_rules]
            with pytest.raises(RevisionConflictError):
                await repository.save_meal_plan_rules("A stale edit", 1)
            with pytest.raises(RepositoryError):
                await repository.request("PATCH", "meal_plan_rule_revisions", params={"id": f"eq.{first_rules['id']}"}, json={"text": "Overwrite history"})
            first = await repository.save_meal_plan({
                "weekStart": first_week, "status": "draft",
                "ruleRevisionId": first_rules["id"],
                "entries": [{"date": first_week, "slot": "dinner", "meal": "Lentil bowls"}],
            })
            assert first["entries"][0]["meal"] == "Lentil bowls"
            assert first["ruleRevision"] == first_rules
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
            first_edit = await repository.save_meal_plan({"id": first["id"], "weekStart": first_week,
                "entries": [{"date": first_week, "slot": "dinner", "meal": "Changed by hand"}]})
            assert first_edit["ruleRevision"] == first_rules
            assert [plan["weekStart"] for plan in await repository.get_recent_meal_plans("2030-02-18")] == [second_week, first_week]

            days = [{"day": day, "mode": "quick"} for day in (
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
            )]
            assert (await repository.save_weekly_schedule({"weekStart": second_week, "days": days, "notes": "Guests Saturday."}))["days"] == days
            days[0]["mode"] = "busy"
            assert (await repository.save_weekly_schedule({"weekStart": second_week, "days": days}))["days"][0]["mode"] == "busy"
            assert (await repository.get_weekly_schedule(second_week))["notes"] == "Guests Saturday."

            # Reads and writes use the selected household, even for known IDs.
            memberships = await repository.create_household("Another kitchen")
            second_household_id = memberships["activeHouseholdId"]
            assert await repository.get_meal_plan_rules(first_rules["id"]) is None
            assert await repository.get_meal_plan_rule_history() == []
            assert await repository.get_recent_meal_plans("2030-02-18") == []
            with pytest.raises(RepositoryError):
                await repository.save_meal_plan({"weekStart": first_week, "ruleRevisionId": first_rules["id"], "entries": []})
            other_rules = await repository.save_meal_plan_rules("Sunday pulav.", 0)
            other_plan = await repository.save_meal_plan({"weekStart": first_week, "ruleRevisionId": other_rules["id"], "entries": []})
            assert other_plan["ruleRevision"] == other_rules
            await repository.switch_household(household_id)
            assert (await repository.get_meal_plan(first_week))["ruleRevision"] == first_rules
        finally:
            for cleanup_id in (extra_household_id, second_household_id, household_id):
                if not cleanup_id:
                    continue
                removed = await client.delete(
                    "/rest/v1/households", params={"id": f"eq.{cleanup_id}"},
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


@pytest.mark.asyncio
async def test_local_supabase_meal_library_roundtrip_validation_and_rls():
    from app.application.errors import ApplicationError
    url, anon, secret = (os.environ.get(key) for key in ('MEAL_PREP_TEST_SUPABASE_URL', 'MEAL_PREP_TEST_ANON_KEY', 'MEAL_PREP_TEST_SERVICE_ROLE_KEY'))
    if not all((url, anon, secret)): pytest.skip('local Supabase test credentials are not configured')
    admin = {'apikey': secret, 'Authorization': f'Bearer {secret}'}
    users, homes, repos = [], [], []
    async with httpx.AsyncClient(base_url=url, timeout=20) as client:
        try:
            for _ in range(2):
                email, password = f'meal-library-{uuid4()}@example.test', str(uuid4())
                created = await client.post('/auth/v1/admin/users', headers=admin, json={'email': email, 'password': password, 'email_confirm': True})
                assert created.status_code in (200,201), created.text
                users.append(created.json()['id'])
                login = await client.post('/auth/v1/token', params={'grant_type':'password'}, headers={'apikey':anon}, json={'email':email,'password':password})
                assert login.status_code == 200
                repo = SupabaseRepository(Settings(supabase_url=url, supabase_anon_key=anon, auth_required=True),login.json()['access_token'])
                repos.append(repo); homes.append((await repo.get_household_context())['householdId'])
            repo, other = repos
            food, planning = RecipePantryService(repo), PlanningService(repo)
            recipe = await food.save_recipe({'title':'Dal','servings':4,'ingredients':[{'name':'Lentils','quantity':200,'unit':'g'}]})
            ready = await food.save_recipe({'title':'Rotis','kind':'ready_food','instructions':['Heat and serve']})
            assert (await food.browse_recipe_library(item_type='ready_food'))['items'][0]['id'] == ready['id']
            shared = await food.create_recipe_share(ready['id'])
            copied_id = await other.copy_shared_recipe(shared['token'])
            assert (await other.get_recipe(copied_id))['kind'] == 'ready_food'
            for value in ({'kind':'unknown'}, {'kind':'ready_food','ingredients':[{'name':'Flour'}]}):
                with pytest.raises(RepositoryError):
                    await repo.request('PATCH','recipes',params={'id':f"eq.{ready['id']}"},json=value)
            meal = await planning.meals.save({'name':'Dal and rotis','servings':4,'notes':'School pickup dinner','components':[
                {'name':'Dal','quantity':4,'unit':'servings','source':'cook','recipeId':recipe['id']},
                {'name':'Rotis','quantity':8,'unit':'pieces','action':'heat','source':'ready','recipeId':ready['id']}]})
            assert (await planning.meals.search('ROTIS'))['items'] == [meal]
            assert (await planning.meals.search('pickup'))['total'] == 1
            # Full library search and pagination, including beyond the first 50 choices.
            await repo.request('POST','meals', json=[{'household_id':homes[0],'name':f'Dinner {i}','servings':1,'components':[{
                'id':str(uuid4()),'name':'Popcorn','source':'ready','action':'serve'}]} for i in range(51)])
            assert (await planning.meals.search())['total'] == 52
            assert len((await planning.meals.search(offset=50))['items']) == 2
            week='2030-02-04'
            plan=await planning.plan_saved_meal(week,meal['id'],week,'dinner',8)
            entry=plan['entries'][0]
            assert entry['sourceMeal'] == {key:meal[key] for key in ('id','name','revision')}
            assert entry['components'][0]['quantity'] == 8
            assert {row['name']:row['quantity'] for row in (await planning.preview_shopping(week))['items']} == {'Lentils':400,'Rotis':16}
            changed=await planning.meals.save({**meal,'name':'New dinner'})
            assert changed['revision'] == 2
            assert await planning.get_meal_plan(week) == plan
            await planning.meals.archive(meal['id'])
            assert (await planning.meals.search('rotis'))['total'] == 0
            with pytest.raises(ApplicationError,match='Archived'): await planning.plan_saved_meal(week,meal['id'],week,'dinner')
            updated=await planning.update_plan_item(week,'meal',{'id':entry['id'],'notes':'Still editable'})
            assert updated['entries'][0]['sourceMeal'] == entry['sourceMeal']
            with pytest.raises(RepositoryError): await repo.save_meal(meal)
            # Unknown/foreign JSON references are rejected by both service and direct-table triggers.
            foreign_recipe=await RecipePantryService(other).save_recipe({'title':'Private soup','servings':2})
            foreign=await PlanningService(other).meals.save({'name':'Private meal','servings':2,'components':[{'name':'Private soup','source':'cook','recipeId':foreign_recipe['id']}]})
            assert await other.get_meal(meal['id']) is None
            assert await other.request('GET','meals',params={'household_id':f'eq.{homes[0]}'}) == []
            with pytest.raises(RepositoryError): await other.save_meal({**changed,'name':'Foreign overwrite'})
            before=await repo.search_meals('',50,0)
            for bad in [
                [{'id':str(uuid4()),'name':'Bad recipe','source':'cook','action':'cook','recipeId':foreign_recipe['id']}],
                [{'id':str(uuid4()),'name':'Bad task','source':'task','action':'serve','taskId':str(uuid4())}],
                [{'id':str(uuid4()),'name':'Wrong ready-food source','source':'cook','action':'cook','recipeId':ready['id']}],
                [{'id':str(uuid4()),'name':'Bad quantity','source':'ready','action':'serve','quantity':-1}],
            ]:
                with pytest.raises(RepositoryError): await repo.request('POST','meals',json={'household_id':homes[0],'name':'Bad meal','servings':1,'components':bad})
            assert await repo.search_meals('',50,0) == before
            with pytest.raises(RepositoryError): await other.request('POST','meals',json={'household_id':homes[0],'name':'Forbidden','servings':1,'components':foreign['components']})
            # Origin provenance cannot cross households, including writes bypassing the service.
            with pytest.raises(RepositoryError): await repo.request('POST','meal_plan_entries',json={
                'meal_plan_id':plan['id'],'planned_for':week,'slot':'dinner','title':'Forged origin',
                'components':[],'source_meal':{key:foreign[key] for key in ('id','name','revision')}})
            with pytest.raises(RepositoryError): await repo.request('PATCH','meal_plan_entries',params={'id':f"eq.{entry['id']}"},json={'source_meal':None})
            completed=await planning.complete_item(week,'meal',entry['id'])
            with pytest.raises(RepositoryError): await repo.save_meal_plan({**completed['plan'],'entries':[{**completed['plan']['entries'][0],'sourceMeal':None}]})
            assert await planning.get_meal_plan(week) == completed['plan']
            assert await repo.get_pantry() == []
        finally:
            for home in homes:
                deleted=await client.delete('/rest/v1/households',headers=admin,params={'id':f'eq.{home}'})
                assert deleted.status_code in (200,204),deleted.text
            for user in users:
                deleted=await client.delete(f'/auth/v1/admin/users/{user}',headers=admin)
                assert deleted.status_code in (200,204),deleted.text

@pytest.mark.asyncio
async def test_local_sharing_hub_direct_mentions_and_public_broadcasts():
    """Private recipients, mention scope, and public bearer links stay separate."""
    from app.application.meal_library import MealLibrary
    from app.sharing import read_shared_food
    url, anon, secret = (os.environ.get(key) for key in
        ('MEAL_PREP_TEST_SUPABASE_URL', 'MEAL_PREP_TEST_ANON_KEY', 'MEAL_PREP_TEST_SERVICE_ROLE_KEY'))
    if not all((url, anon, secret)):
        pytest.skip('local Supabase test credentials are not configured')
    admin = {'apikey': secret, 'Authorization': f'Bearer {secret}'}
    users = []
    async with httpx.AsyncClient(base_url=url, timeout=20) as client:
        try:
            repos = []
            for role in ('owner', 'friend', 'outsider'):
                email, password = f'hub-{role}-{uuid4()}@example.test', str(uuid4())
                response = await client.post('/auth/v1/admin/users', headers=admin,
                    json={'email': email, 'password': password, 'email_confirm': True})
                assert response.status_code in (200, 201), response.text
                users.append(response.json()['id'])
                login = await client.post('/auth/v1/token', params={'grant_type': 'password'},
                    headers={'apikey': anon}, json={'email': email, 'password': password})
                assert login.status_code == 200
                repo = SupabaseRepository(Settings(supabase_url=url, supabase_anon_key=anon, auth_required=True),
                    login.json()['access_token'])
                await repo.get_household_context()
                repos.append((repo, email))
            (owner, _), (friend, friend_email), (outsider, _) = repos
            own, peer, stranger = CircleService(owner), CircleService(friend), CircleService(outsider)
            recipe = await RecipePantryService(owner).save_recipe({'title': 'Hub dal', 'servings': 4,
                'ingredients': [{'name': 'Lentils', 'quantity': 1, 'unit': 'cup'}]})
            meal = await MealLibrary(owner).save({'name': 'Dal dinner', 'servings': 4,
                'components': [{'id': str(uuid4()), 'name': 'Dal', 'source': 'cook',
                    'action': 'cook', 'recipeId': recipe['id']}]})
            circle = await own.create_circle('Small table')
            await own.invite_friend(circle['id'], friend_email)
            await peer.respond_invitation(circle['id'], True)
            candidates = (await own.mention_candidates(circle['id']))['items']
            assert {item['id'] for item in candidates} == {users[0], users[1]}
            reviewed_audience = sorted(f"{item['userId']}:{item['membershipId']}" for item in
                (await own.list_circles())['items'][0]['audience'])
            assert await outsider.circle_mention_candidates(circle['id']) == []
            with pytest.raises(RepositoryError, match='Mentioned friend'):
                await own.send_message(circle['id'], 'Hello', mention_ids=[users[2]])
            attached = await own.send_message(circle['id'], 'Try this', 'meal', meal['id'], [users[1]], reviewed_audience)
            assert attached['kind'] == 'meal' and attached['snapshot']['meal']['name'] == 'Dal dinner'
            assert (await peer.get_shared_item(attached['id']))['snapshot']['recipes'][0]['title'] == 'Hub dal'
            assert (await friend.request('GET', 'notifications', params={'select': 'kind', 'kind': 'eq.circle_mention'}))
            await own.invite_friend(circle['id'], repos[2][1])
            await stranger.respond_invitation(circle['id'], True)
            with pytest.raises(RepositoryError, match='Circle audience changed'):
                await own.send_message(circle['id'], 'Stale share', 'recipe', recipe['id'],
                    expected_audience=reviewed_audience)
            await PlanningService(owner).save_meal_plan({'weekStart': '2030-02-04', 'entries': [
                {'date': '2030-02-04', 'slot': 'dinner', 'meal': 'Dal'}]})
            with pytest.raises(RepositoryError, match='Circle audience changed'):
                await own.share_week(circle['id'], '2030-02-04', reviewed_audience)
            assert not any(item['snapshot'].get('text') == 'Stale share' for item in
                (await own.list_shared_with_me(circle_id=circle['id']))['items'])
            assert users[2] not in (await own.get_shared_item(attached['id']))['recipientUserIds']
            with pytest.raises(RepositoryError, match='Mentioned friend'):
                await own.comment(attached['id'], 'Can you see this?', mention_ids=[users[2]])
            direct = await own.share_direct(friend_email, 'recipe', recipe['id'])
            assert direct['roomType'] == 'direct'
            assert (await peer.list_direct_shares())['items'][0]['id'] == direct['id']
            assert (await peer.list_circles())['items'][0]['name'] == 'Small table'
            assert (await peer.get_shared_item(direct['id']))['snapshot']['recipe']['title'] == 'Hub dal'
            with pytest.raises(RepositoryError):
                await stranger.get_shared_item(direct['id'])
            with pytest.raises(RepositoryError):
                await outsider.circle_invite(direct['circleId'], users[2])
            await peer.comment(direct['id'], 'Sounds good')
            assert (await own.get_shared_item(direct['id']))['comments'][0]['body'] == 'Sounds good'
            direct_meal = await own.share_direct(friend_email, 'meal', meal_id=meal['id'])
            assert (await peer.get_shared_item(direct_meal['id']))['snapshot']['meal']['name'] == 'Dal dinner'
            with pytest.raises(RepositoryError):
                await own.share_direct(friend_email, 'meal', meal_id=str(uuid4()))
            public = await RecipePantryService(owner).create_meal_share(meal['id'])
            links = await RecipePantryService(owner).list_public_shares()
            assert links[0]['token'] == public['token'] and links[0]['kind'] == 'meal'
            assert (await read_shared_food(public['token'], Settings(supabase_url=url,
                supabase_anon_key=anon, auth_required=True)))['meal']['name'] == 'Dal dinner'
            assert await RecipePantryService(owner).revoke_public_share(public['id'])
            assert await read_shared_food(public['token'], Settings(supabase_url=url,
                supabase_anon_key=anon, auth_required=True)) is None
            assert (await RecipePantryService(owner).list_public_shares())[0]['token'] is None
            with pytest.raises(ApplicationError):
                await RecipePantryService(friend).revoke_public_share(public['id'])
        finally:
            for user_id in users:
                await client.delete(f'/auth/v1/admin/users/{user_id}', headers=admin)
