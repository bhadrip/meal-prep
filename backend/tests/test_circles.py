from uuid import uuid4

import pytest

from app.application.errors import ApplicationError, RepositoryError
from app.application.services import CircleService
from app.infrastructure.repositories import DemoRepository


@pytest.mark.asyncio
async def test_week_snapshot_contains_all_slots_and_referenced_food_without_private_data():
    owner = DemoRepository()
    owner.user_id = "owner"
    owner._circles = {}
    owner._circle_posts = {}
    owner._circle_comments = {}
    owner._circle_saves = {}
    owner._recipes = [{**owner._recipes[0], "private_note": "do not share"}]
    circle = await CircleService(owner).create_circle("Friends")
    await CircleService(owner).invite_friend(circle["id"], "friend@example.test")
    with pytest.raises(ApplicationError, match="already invited"):
        await CircleService(owner).invite_friend(circle["id"], "friend@example.test")
    friend = owner.as_user("friend@example.test")
    assert (await CircleService(friend).list_shared_with_me())["items"] == []
    await CircleService(friend).respond_invitation(circle["id"], True)
    recipe_id = owner._recipes[0]["id"]
    ready = await owner.save_recipe({"title": "Yogurt", "kind": "ready_food", "ingredients": [], "instructions": ["Open"]})
    week = "2030-02-04"
    await owner.save_meal_plan({"weekStart": week, "entries": [
        {"id": str(uuid4()), "date": week, "slot": "breakfast", "meal": "Yogurt bowl", "components": [{"name": "Yogurt", "recipeId": ready["id"], "source": "ready"}]},
        {"id": str(uuid4()), "date": week, "slot": "dinner", "meal": "Paneer rice", "components": [{"name": "Paneer", "recipeId": recipe_id, "source": "cook", "pantryItemId": str(uuid4()), "privateNote": "hidden"}]},
        {"id": str(uuid4()), "date": week, "slot": "snack", "meal": "Leftovers", "components": [{"name": "Paneer", "recipeId": recipe_id, "source": "cook"}]},
    ], "tasks": [{"id": str(uuid4()), "title": "private prep"}]})
    shared = await CircleService(owner).share_week(circle["id"], week)
    post = await CircleService(friend).get_shared_item(shared["id"])
    assert {entry["slot"] for entry in post["snapshot"]["entries"]} == {"breakfast", "dinner", "snack"}
    assert {recipe["title"] for recipe in post["snapshot"]["recipes"]} == {"Yogurt", "Paneer rice bowls"}
    assert "private prep" not in str(post)
    assert "do not share" not in str(post)
    assert "pantryItemId" not in str(post) and "privateNote" not in str(post)
    await owner.save_recipe({"id": recipe_id, "title": "Changed"})
    assert (await CircleService(friend).get_shared_item(shared["id"]))["snapshot"]["recipes"][0]["title"] != "Changed"
    feed = await CircleService(friend).list_shared_with_me()
    assert feed["items"][0]["id"] == shared["id"]


@pytest.mark.asyncio
async def test_circle_access_comments_and_recipe_copy_are_scoped():
    owner = DemoRepository()
    owner.user_id = "owner"
    owner._circles = {}
    owner._circle_posts = {}
    owner._circle_comments = {}
    owner._circle_saves = {}
    circle = await CircleService(owner).create_circle("Friends")
    recipe_id = owner._recipes[0]["id"]
    shared = await CircleService(owner).share_recipe(circle["id"], recipe_id)
    outsider = owner.as_user("outsider@example.test")
    with pytest.raises(RepositoryError):
        await CircleService(outsider).get_shared_item(shared["id"])
    with pytest.raises(RepositoryError):
        await CircleService(outsider).comment(shared["id"], "Looks good")
    await CircleService(owner).invite_friend(circle["id"], "friend@example.test")
    friend = owner.as_user("friend@example.test")
    await CircleService(friend).respond_invitation(circle["id"], True)
    with pytest.raises(ApplicationError):
        await CircleService(friend).comment(shared["id"], "  ")
    with pytest.raises(RepositoryError):
        await CircleService(friend).comment(shared["id"], "Question", "meal", str(uuid4()))
    await CircleService(friend).comment(shared["id"], "How spicy is this?")
    assert (await CircleService(owner).get_shared_item(shared["id"]))["comments"][0]["body"] == "How spicy is this?"
    copied = await CircleService(friend).save_shared_recipe(shared["id"], recipe_id)
    assert copied["recipeId"] != recipe_id
    assert copied["alreadySaved"] is False
    assert (await CircleService(friend).save_shared_recipe(shared["id"], recipe_id))["recipeId"] == copied["recipeId"]
    await friend.archive_recipe(copied["recipeId"])
    assert (await CircleService(friend).get_shared_item(shared["id"]))["savedRecipeIds"] == {}
    replacement = await CircleService(friend).save_shared_recipe(shared["id"], recipe_id)
    assert replacement["recipeId"] != copied["recipeId"] and not replacement["alreadySaved"]
    another_post = await CircleService(owner).share_recipe(circle["id"], recipe_id)
    assert (await CircleService(friend).get_shared_item(another_post["id"]))["savedRecipeIds"][recipe_id] == replacement["recipeId"]
    assert (await CircleService(friend).save_shared_recipe(another_post["id"], recipe_id))["recipeId"] == replacement["recipeId"]
    with pytest.raises(RepositoryError):
        await CircleService(friend).save_shared_recipe(shared["id"], str(uuid4()))
    await CircleService(owner).remove_friend(circle["id"], friend.user_id)
    with pytest.raises(RepositoryError):
        await CircleService(friend).get_shared_item(shared["id"])
    with pytest.raises(RepositoryError):
        await CircleService(friend).leave_circle(circle["id"])
    await CircleService(owner).invite_friend(circle["id"], friend.user_id)
    await CircleService(friend).respond_invitation(circle["id"], True)
    assert (await CircleService(friend).get_shared_item(shared["id"]))["id"] == shared["id"]
    await CircleService(friend).leave_circle(circle["id"])
    with pytest.raises(RepositoryError):
        await CircleService(friend).get_shared_item(shared["id"])
    await CircleService(owner).revoke_share(shared["id"])
    with pytest.raises(RepositoryError):
        await CircleService(friend).get_shared_item(shared["id"])


@pytest.mark.asyncio
async def test_sharing_requires_a_real_monday_plan():
    repository = DemoRepository()
    circle = await CircleService(repository).create_circle("Friends")
    with pytest.raises(ApplicationError, match="Monday"):
        await CircleService(repository).share_week(circle["id"], "2030-02-05")
    with pytest.raises(ApplicationError, match="valid"):
        await CircleService(repository).share_week(circle["id"], "not-a-week")
    with pytest.raises(RepositoryError, match="not found"):
        await CircleService(repository).share_week(circle["id"], "2030-02-04")


@pytest.mark.asyncio
async def test_shared_inspiration_pages_across_circles_and_filters_by_kind():
    repository = DemoRepository()
    service = CircleService(repository)
    first = await service.create_circle("Friends one")
    second = await service.create_circle("Friends two")
    week = (await repository.get_meal_plan())["weekStart"]
    older = await service.share_week(first["id"], week)
    newer = await service.share_recipe(second["id"], repository._recipes[0]["id"])
    page = await service.list_shared_with_me(limit=1)
    assert [item["id"] for item in page["items"]] == [newer["id"]]
    assert page["nextOffset"] == 1
    assert [item["id"] for item in (await service.list_shared_with_me(limit=1, offset=1))["items"]] == [older["id"]]
    assert (await service.list_shared_with_me(kind="week"))["items"][0]["id"] == older["id"]
    with pytest.raises(ApplicationError):
        await service.list_shared_with_me(kind="pantry")
