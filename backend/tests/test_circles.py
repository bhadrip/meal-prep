from uuid import uuid4

import pytest

from app.application.errors import ApplicationError, RepositoryError
from app.application.services import CircleService
from app.infrastructure.repositories import DemoRepository


@pytest.mark.asyncio
async def test_circle_group_message_and_thread_are_scoped_to_members():
    owner = DemoRepository()
    owner.user_id = "owner"
    owner._circles = {}
    owner._circle_posts = {}
    owner._circle_comments = {}
    service = CircleService(owner)
    circle = await service.create_circle("Dinner friends")
    another = await service.create_circle("Other friends")
    friend = owner.as_user("friend@example.test")
    outsider = owner.as_user("outsider@example.test")
    await service.invite_friend(circle["id"], friend.user_id)
    await CircleService(friend).respond_invitation(circle["id"], True)
    with pytest.raises(ApplicationError, match="message"):
        await service.send_message(circle["id"], "  ")
    with pytest.raises(ApplicationError, match="message"):
        await service.send_message(circle["id"], "x" * 2001)
    with pytest.raises(RepositoryError, match="Circle is not available"):
        await CircleService(outsider).send_message(circle["id"], "Can I join?")
    sent = await service.send_message(circle["id"], "  Dinner was great  ")
    assert sent["snapshot"] == {"text": "Dinner was great"}
    assert (await CircleService(friend).list_shared_with_me(circle_id=circle["id"]))["items"][0]["id"] == sent["id"]
    assert (await CircleService(friend).list_shared_with_me(circle_id=another["id"]))["items"] == []
    reply = await CircleService(friend).comment(sent["id"], "What did you make?")
    assert (await service.get_shared_item(sent["id"]))["comments"][0]["id"] == reply["id"]
    assert (await service.list_shared_with_me(circle_id=circle["id"]))["items"][0]["commentCount"] == 1
    with pytest.raises(RepositoryError, match="Shared item was not found"):
        await CircleService(outsider).comment(sent["id"], "Hello")


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
    old_share = await CircleService(owner).share_recipe(circle["id"], recipe_id)
    outsider = owner.as_user("outsider@example.test")
    with pytest.raises(RepositoryError):
        await CircleService(outsider).get_shared_item(old_share["id"])
    with pytest.raises(RepositoryError):
        await CircleService(outsider).comment(old_share["id"], "Looks good")
    await CircleService(owner).invite_friend(circle["id"], "friend@example.test")
    friend = owner.as_user("friend@example.test")
    await CircleService(friend).respond_invitation(circle["id"], True)
    with pytest.raises(RepositoryError):
        await CircleService(friend).get_shared_item(old_share["id"])
    with pytest.raises(RepositoryError):
        await CircleService(friend).comment(old_share["id"], "Can I see this?")
    with pytest.raises(RepositoryError):
        await CircleService(friend).save_shared_recipe(old_share["id"], recipe_id)
    assert (await CircleService(friend).list_shared_with_me())["items"] == []
    shared = await CircleService(owner).share_recipe(circle["id"], recipe_id)
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
        await CircleService(friend).comment(shared["id"], "Still there?")
    with pytest.raises(RepositoryError):
        await CircleService(friend).save_shared_recipe(shared["id"], recipe_id)
    with pytest.raises(RepositoryError):
        await CircleService(friend).leave_circle(circle["id"])
    await CircleService(owner).invite_friend(circle["id"], friend.user_id)
    await CircleService(friend).respond_invitation(circle["id"], True)
    with pytest.raises(RepositoryError):
        await CircleService(friend).get_shared_item(shared["id"])
    fresh = await CircleService(owner).share_recipe(circle["id"], recipe_id)
    assert (await CircleService(friend).get_shared_item(fresh["id"]))["id"] == fresh["id"]
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
    latest = await service.share_recipe(first["id"], repository._recipes[0]["id"])
    first_page = await service.list_shared_with_me(circle_id=first["id"], limit=1)
    assert [item["id"] for item in first_page["items"]] == [latest["id"]]
    assert first_page["nextOffset"] == 1
    assert [item["id"] for item in (await service.list_shared_with_me(circle_id=first["id"], limit=1, offset=1))["items"]] == [older["id"]]
    assert [item["id"] for item in (await service.list_shared_with_me(circle_id=second["id"]))["items"]] == [newer["id"]]
    assert (await CircleService(repository.as_user("outsider@example.test")).list_shared_with_me(circle_id=first["id"]))["items"] == []
    with pytest.raises(ApplicationError, match="valid circle"):
        await service.list_shared_with_me(circle_id="not-a-circle")
    with pytest.raises(ApplicationError):
        await service.list_shared_with_me(kind="pantry")


@pytest.mark.asyncio
async def test_circle_membership_permissions_and_audience_are_constrained():
    owner = DemoRepository()
    owner.user_id = "owner@example.test"
    own = CircleService(owner)
    circle = await own.create_circle("Small circle")
    outsider = owner.as_user("outsider@example.test")
    with pytest.raises(RepositoryError):
        await CircleService(outsider).invite_friend(circle["id"], "third@example.test")
    with pytest.raises(RepositoryError):
        await CircleService(outsider).remove_friend(circle["id"], owner.user_id)
    await own.invite_friend(circle["id"], "friend@example.test")
    pending = owner.as_user("friend@example.test")
    pending_circle = (await CircleService(pending).list_circles())["items"][0]
    assert pending_circle["memberNames"] == [] and pending_circle["memberCount"] == 0
    with pytest.raises(RepositoryError):
        await CircleService(pending).share_recipe(circle["id"], owner._recipes[0]["id"])
    await CircleService(pending).respond_invitation(circle["id"], True)
    member_circle = (await CircleService(pending).list_circles())["items"][0]
    assert set(member_circle["memberNames"]) == {"owner", "friend"}
    assert member_circle["memberCount"] == 2 and member_circle["members"] == []
    with pytest.raises(RepositoryError):
        await CircleService(pending).invite_friend(circle["id"], "third@example.test")
    with pytest.raises(RepositoryError):
        await CircleService(pending).remove_friend(circle["id"], owner.user_id)
    with pytest.raises(RepositoryError):
        await own.leave_circle(circle["id"])
    post = await CircleService(pending).share_recipe(circle["id"], pending._recipes[0]["id"])
    assert (await own.get_shared_item(post["id"]))["createdBy"] == pending.user_id
    with pytest.raises(RepositoryError):
        await own.revoke_share(post["id"])
    await CircleService(pending).revoke_share(post["id"])
    with pytest.raises(RepositoryError):
        await own.get_shared_item(post["id"])
    with pytest.raises(RepositoryError):
        await own.comment(post["id"], "Too late")


@pytest.mark.asyncio
async def test_comments_only_attach_to_targets_in_the_specific_snapshot():
    repo = DemoRepository()
    service = CircleService(repo)
    circle = await service.create_circle("Questions")
    recipe_id = repo._recipes[0]["id"]
    recipe_post = await service.share_recipe(circle["id"], recipe_id)
    week = (await repo.get_meal_plan())["weekStart"]
    week_post = await service.share_week(circle["id"], week)
    week_detail = await service.get_shared_item(week_post["id"])
    meal_id = week_detail["snapshot"]["entries"][0]["id"]
    with pytest.raises(RepositoryError):
        await service.comment(recipe_post["id"], "Wrong meal", "meal", meal_id)
    with pytest.raises(RepositoryError):
        await service.comment(recipe_post["id"], "Wrong recipe", "recipe", str(uuid4()))
    with pytest.raises(RepositoryError):
        await service.comment(recipe_post["id"], "Wrong post", "post", meal_id)
    with pytest.raises(RepositoryError):
        await service.comment(week_post["id"], "Wrong meal", "meal", str(uuid4()))
    with pytest.raises(ApplicationError):
        await service.comment(week_post["id"], "A" * 2001)
    assert (await service.comment(week_post["id"], "A" * 2000, "meal", meal_id))["targetId"] == meal_id
    with pytest.raises(ApplicationError):
        await service.create_circle(" ")
    with pytest.raises(ApplicationError):
        await service.create_circle("A" * 81)
    with pytest.raises(ApplicationError):
        await service.invite_friend(circle["id"], "invalid")
    for limit, offset in ((0, 0), (101, 0), (50, -1)):
        with pytest.raises(ApplicationError):
            await service.list_shared_with_me(limit=limit, offset=offset)


@pytest.mark.asyncio
async def test_circle_activity_caps_stop_invitation_share_and_comment_floods():
    repo = DemoRepository()
    service = CircleService(repo)
    circle = await service.create_circle("Bounded circle")
    for index in range(24):
        await service.invite_friend(circle["id"], f"friend-{index}@example.test")
    with pytest.raises(ApplicationError, match="member limit"):
        await service.invite_friend(circle["id"], "extra@example.test")
    recipe_id = repo._recipes[0]["id"]
    first = await service.share_recipe(circle["id"], recipe_id)
    for index in range(30):
        await service.comment(first["id"], f"Question {index}")
    with pytest.raises(ApplicationError, match="rate limit"):
        await service.comment(first["id"], "Question 31")
    for _ in range(99):
        await service.share_recipe(circle["id"], recipe_id)
    with pytest.raises(ApplicationError, match="share limit"):
        await service.share_recipe(circle["id"], recipe_id)
    for index in range(29):
        await service.create_circle(f"More friends {index}")
    with pytest.raises(ApplicationError, match="Circle limit"):
        await service.create_circle("One too many")


@pytest.mark.asyncio
async def test_comments_can_be_removed_by_author_share_author_or_circle_owner_only():
    owner = DemoRepository()
    owner.user_id = "owner@example.test"
    own = CircleService(owner)
    circle = await own.create_circle("Moderated meals")
    for email in ("author@example.test", "viewer@example.test"):
        await own.invite_friend(circle["id"], email)
    author = owner.as_user("author@example.test")
    viewer = owner.as_user("viewer@example.test")
    await CircleService(author).respond_invitation(circle["id"], True)
    await CircleService(viewer).respond_invitation(circle["id"], True)
    recipe_id = owner._recipes[0]["id"]
    post = await own.share_recipe(circle["id"], recipe_id)
    comment = await CircleService(author).comment(post["id"], "Please remove this")
    with pytest.raises(RepositoryError, match="not found"):
        await CircleService(viewer).delete_comment(comment["id"])
    assert (await own.get_shared_item(post["id"]))["comments"][0]["id"] == comment["id"]
    assert (await own.delete_comment(comment["id"]))["removed"]
    assert (await own.get_shared_item(post["id"]))["comments"] == []
    assert (await CircleService(author).delete_comment(comment["id"]))["removed"]
    own_comment = await own.comment(post["id"], "I can retract this")
    await own.delete_comment(own_comment["id"])
    assert (await own.get_shared_item(post["id"]))["comments"] == []
    former_comment = await CircleService(author).comment(post["id"], "Remove after I leave")
    await own.remove_friend(circle["id"], author.user_id)
    await CircleService(author).delete_comment(former_comment["id"])
    assert (await own.get_shared_item(post["id"]))["comments"] == []
    await own.invite_friend(circle["id"], author.user_id)
    await CircleService(author).respond_invitation(circle["id"], True)
    authors_post = await CircleService(author).share_recipe(circle["id"], recipe_id)
    peer_comment = await CircleService(viewer).comment(authors_post["id"], "Off topic")
    await CircleService(author).delete_comment(peer_comment["id"])
    assert (await own.get_shared_item(authors_post["id"]))["comments"] == []
    with pytest.raises(RepositoryError, match="not found"):
        await own.delete_comment(str(uuid4()))
