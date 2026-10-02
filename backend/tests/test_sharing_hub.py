from uuid import uuid4

import pytest

from app.application.circles import CircleService
from app.application.errors import ApplicationError, RepositoryError
from app.application.meal_library import MealLibrary
from app.application.services import RecipePantryService
from app.infrastructure.repositories import DemoRepository


@pytest.mark.asyncio
async def test_direct_share_is_one_to_one_thread_and_not_a_group():
    owner = DemoRepository()
    owner.user_id = 'owner@example.test'
    owner._circles = {}
    owner._circle_posts = {}
    owner._circle_comments = {}
    recipe_id = owner._recipes[0]['id']
    meal = await MealLibrary(owner).save({'name': 'Dinner bowl', 'servings': 2,
        'components': [{'id': str(uuid4()), 'name': 'Paneer', 'source': 'cook',
                        'action': 'cook', 'recipeId': recipe_id}]})
    friend = owner.as_user('friend@example.test')
    outsider = owner.as_user('outsider@example.test')
    shared = await CircleService(owner).share_direct(friend.user_id, 'meal', meal_id=meal['id'])
    assert shared['roomType'] == 'direct'
    assert (await CircleService(friend).list_direct_shares())['items'][0]['id'] == shared['id']
    assert (await CircleService(friend).list_circles())['items'] == []
    assert (await CircleService(friend).get_shared_item(shared['id']))['snapshot']['meal']['name'] == 'Dinner bowl'
    await CircleService(friend).comment(shared['id'], 'Can I make this ahead?')
    assert (await CircleService(owner).get_shared_item(shared['id']))['comments'][0]['body'] == 'Can I make this ahead?'
    with pytest.raises(RepositoryError, match='Shared item was not found'):
        await CircleService(outsider).get_shared_item(shared['id'])
    with pytest.raises(RepositoryError, match='invitation is not available'):
        await CircleService(owner).invite_friend(shared['circleId'], outsider.user_id)
    with pytest.raises(ApplicationError, match='one recipe or weekly plan'):
        await CircleService(owner).share_direct(friend.user_id, 'meal', recipe_id=recipe_id)
    await CircleService(owner).revoke_share(shared['id'])
    assert (await CircleService(friend).list_direct_shares())['items'] == []


@pytest.mark.asyncio
async def test_chat_food_attachment_and_mentions_validate_access():
    owner = DemoRepository()
    owner.user_id = 'owner@example.test'
    owner._circles = {}
    owner._circle_posts = {}
    owner._circle_comments = {}
    service = CircleService(owner)
    circle = await service.create_circle('Dinner friends')
    friend = owner.as_user('friend@example.test')
    await service.invite_friend(circle['id'], friend.user_id)
    await CircleService(friend).respond_invitation(circle['id'], True)
    recipe_id = owner._recipes[0]['id']
    sent = await service.send_message(circle['id'], 'Try this', 'recipe', recipe_id, [friend.user_id])
    assert sent['kind'] == 'recipe' and sent['snapshot']['caption'] == 'Try this'
    original = (await CircleService(friend).get_shared_item(sent['id']))['snapshot']['recipe']
    assert original['id'] == recipe_id
    await owner.save_recipe({**(await owner.get_recipe(recipe_id)), 'title': 'Changed after sharing'})
    assert (await CircleService(friend).get_shared_item(sent['id']))['snapshot']['recipe'] == original
    with pytest.raises(RepositoryError, match='Shared item was not found'):
        await CircleService(owner.as_user('outsider@example.test')).get_shared_item(sent['id'])
    assert {item['id'] for item in (await CircleService(friend).mention_candidates(circle['id']))['items']} == {owner.user_id, friend.user_id}
    with pytest.raises(RepositoryError, match='Mentioned friend'):
        await service.send_message(circle['id'], 'Hi', mention_ids=['outsider@example.test'])
    with pytest.raises(RepositoryError, match='Mentioned friend'):
        await service.comment(sent['id'], 'Hi', mention_ids=['outsider@example.test'])
    with pytest.raises(RepositoryError, match='Recipe was not found'):
        await service.send_message(circle['id'], '', 'recipe', str(uuid4()))
    audience = sorted(f"{item['userId']}:{item['membershipId']}" for item in
                      (await service.list_circles())['items'][0]['audience'])
    late_friend = owner.as_user('late@example.test')
    await service.invite_friend(circle['id'], late_friend.user_id)
    await CircleService(late_friend).respond_invitation(circle['id'], True)
    with pytest.raises(RepositoryError, match='Circle audience changed'):
        await service.send_message(circle['id'], 'Share', 'recipe', recipe_id, expected_audience=audience)
    assert late_friend.user_id not in (await service.get_shared_item(sent['id']))['recipientUserIds']
    with pytest.raises(RepositoryError, match='Mentioned friend'):
        await service.comment(sent['id'], 'Welcome', mention_ids=[late_friend.user_id])


@pytest.mark.asyncio
async def test_reviewed_week_rejects_changed_circle_audience_without_publishing():
    owner = DemoRepository()
    owner.user_id = 'owner@example.test'
    owner._circles = {}
    owner._circle_posts = {}
    service = CircleService(owner)
    circle = await service.create_circle('Sunday table')
    await owner.save_meal_plan({'weekStart': '2030-02-04', 'entries': [
        {'date': '2030-02-04', 'slot': 'dinner', 'meal': 'Rice'}], 'tasks': []})
    audience = sorted(f"{item['userId']}:{item['membershipId']}" for item in
                      (await service.list_circles())['items'][0]['audience'])
    late_friend = owner.as_user('late@example.test')
    await service.invite_friend(circle['id'], late_friend.user_id)
    await CircleService(late_friend).respond_invitation(circle['id'], True)
    with pytest.raises(RepositoryError, match='Circle audience changed'):
        await service.share_week(circle['id'], '2030-02-04', audience)
    assert (await service.list_shared_with_me(circle_id=circle['id']))['items'] == []


@pytest.mark.asyncio
async def test_public_meal_link_can_be_recovered_and_revoked_without_comments():
    owner = DemoRepository()
    owner.user_id = 'owner@example.test'
    meal = await MealLibrary(owner).save({'name': 'Sunday rice', 'servings': 2,
        'components': [{'id': str(uuid4()), 'name': 'Rice', 'source': 'external', 'action': 'serve'}]})
    food = RecipePantryService(owner)
    shared = await food.create_meal_share(meal['id'])
    listed = await food.list_public_shares()
    assert any(item['id'] == shared['id'] and item['token'] == shared['token'] for item in listed)
    assert DemoRepository.read_shared_food(shared['token'])['meal']['name'] == 'Sunday rice'
    with pytest.raises(ApplicationError, match='Meal was not found'):
        await food.create_meal_share(str(uuid4()))
    with pytest.raises(ApplicationError, match='future ISO'):
        await food.create_meal_share(meal['id'], '2020-01-01T00:00:00Z')
    other = RecipePantryService(owner.as_user('other@example.test'))
    with pytest.raises(ApplicationError, match='Share was not found'):
        await other.revoke_public_share(shared['id'])
    await food.revoke_public_share(shared['id'])
    assert DemoRepository.read_shared_food(shared['token']) is None
    assert next(item for item in await food.list_public_shares() if item['id'] == shared['id'])['token'] is None
