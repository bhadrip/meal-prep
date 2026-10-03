from copy import deepcopy
from uuid import uuid4

import pytest

from app.application.errors import ApplicationError
from app.application.services import PlanningService, RecipePantryService
from app.infrastructure.repositories import DemoRepository

WEEK = '2030-02-04'


async def example():
    repo = DemoRepository()
    repo._pantry = []
    food = RecipePantryService(repo)
    dal = await food.save_recipe({'title': 'Dal', 'servings': 4, 'ingredients': [{'name': 'Lentils', 'quantity': 200, 'unit': 'g'}]})
    salad = await food.save_recipe({'title': 'Salad', 'servings': 2, 'ingredients': [{'name': 'Carrots', 'quantity': 100, 'unit': 'g'}]})
    service = PlanningService(repo)
    meal = await service.meals.save({'name': 'Roti dinner', 'servings': 4, 'notes': 'Easy family dinner', 'components': [
        {'name': 'Rotis', 'quantity': 8, 'unit': 'pieces', 'action': 'heat'},
        {'name': 'Dal', 'quantity': 4, 'unit': 'servings', 'source': 'cook', 'action': 'cook', 'recipeId': dal['id']},
        {'name': 'Salad', 'quantity': 4, 'unit': 'servings', 'source': 'cook', 'recipeId': salad['id']},
        {'name': 'Yogurt', 'quantity': 200, 'unit': 'g'}]})
    return repo, service, food, dal, meal


@pytest.mark.asyncio
async def test_saved_meal_scales_copies_and_recipe_demand_without_consuming_stock():
    repo, service, food, _, meal = await example()
    stock = await food.update_pantry_item({'name': 'Rotis', 'quantity': 10, 'unit': 'pieces', 'quantityConfidence': 'exact'})
    before = await repo.get_pantry()
    plan = await service.plan_saved_meal(WEEK, meal['id'], WEEK, 'dinner', 8)
    entry = plan['entries'][0]
    assert entry['sourceMeal'] == {key: meal[key] for key in ('id', 'name', 'revision')}
    assert [row['quantity'] for row in entry['components']] == [16, 8, 8, 400]
    assert not set(row['id'] for row in entry['components']) & set(row['id'] for row in meal['components'])
    preview = await service.preview_shopping(WEEK)
    assert {row['name']: row['quantity'] for row in preview['items']} == {'Rotis': 6, 'Lentils': 400, 'Carrots': 400, 'Yogurt': 400}
    assert preview['warnings'] == []
    assert await repo.get_pantry() == before
    plan = await service.plan_saved_meal(WEEK, meal['id'], '2030-02-05', 'dinner')
    assert len(plan['entries']) == 2
    assert plan['entries'][0]['id'] != plan['entries'][1]['id']
    assert not set(row['id'] for row in plan['entries'][0]['components']) & set(row['id'] for row in plan['entries'][1]['components'])
    assert (await service.get_context(WEEK))['savedMeals']['items'][0]['id'] == meal['id']
    # Pantry references belong to this copy, not the library.
    await service.update_plan_item(WEEK, 'meal', {'id': entry['id'], 'components': [{**entry['components'][0], 'pantryItemId': stock['id']}, *entry['components'][1:]]})
    assert (await service.meals.get(meal['id'])) == meal


@pytest.mark.asyncio
async def test_quick_plan_uses_selected_food_with_servings_and_occurrence_notes_only():
    repo, service, food, dal, meal = await example()
    planned = await service.plan_recipe(WEEK, dal['id'], WEEK, 'dinner', 2, 'Extra chili')
    entry = planned['entries'][0]
    assert entry['meal'] == 'Dal' and entry['servings'] == 2 and entry['notes'] == 'Extra chili'
    assert entry['components'][0]['recipeId'] == dal['id']
    assert entry['components'][0]['recipeSnapshot']['ingredients'][0]['quantity'] == 200
    assert (await food.get_recipe(dal['id']))['title'] == 'Dal'
    planned = await service.plan_saved_meal(WEEK, meal['id'], '2030-02-05', 'dinner', 2, '')
    saved_entry = planned['entries'][1]
    assert saved_entry['notes'] == '' and saved_entry['servings'] == 2
    assert saved_entry['components'][0]['quantity'] == 4
    assert (await service.meals.get(meal['id']))['notes'] == 'Easy family dinner'
    ready_food = await food.save_recipe({'title': 'Ready rotis', 'kind': 'ready_food'})
    planned = await service.plan_recipe(WEEK, ready_food['id'], '2030-02-06', 'dinner', 3)
    assert planned['entries'][2]['components'][0]['source'] == 'ready'
    assert planned['entries'][2]['components'][0]['action'] == 'serve'
    before = await service.get_meal_plan(WEEK)
    for recipe_id, servings in ((str(uuid4()), 2), (dal['id'], -1)):
        with pytest.raises(ApplicationError):
            await service.plan_recipe(WEEK, recipe_id, WEEK, 'dinner', servings)
        assert await service.get_meal_plan(WEEK) == before
    with pytest.raises(ApplicationError):
        await service.plan_saved_meal(WEEK, meal['id'], WEEK, 'dinner', 2, 'x' * 3001)
    assert await service.get_meal_plan(WEEK) == before
    await food.archive_recipe(dal['id'])
    with pytest.raises(ApplicationError, match='Recipe was not found'):
        await service.plan_recipe(WEEK, dal['id'], WEEK, 'dinner')
    assert await service.get_meal_plan(WEEK) == before


@pytest.mark.asyncio
async def test_combining_recipes_and_ready_food_keeps_links_and_rejects_bad_selections_atomically():
    repo, service, food, dal, _ = await example()
    ready = await food.save_recipe({'title': 'Ready rotis', 'kind': 'ready_food', 'servings': 4})
    plan = await service.plan_combination(WEEK, [dal['id'], ready['id']], WEEK, 'dinner', 3, 'Serve together')
    entry = plan['entries'][0]
    assert entry['meal'] == 'Dal + Ready rotis'
    assert entry['servings'] == 3 and entry['notes'] == 'Serve together'
    assert [(row['recipeId'], row['quantity'], row['source']) for row in entry['components']] == [
        (dal['id'], 3, 'cook'), (ready['id'], 3, 'ready')]
    assert [row['recipeSnapshot']['title'] for row in entry['components']] == ['Dal', 'Ready rotis']
    assert await food.get_recipe(dal['id'])
    before = deepcopy(plan)
    invalid = [[dal['id'], dal['id']], [dal['id'], str(uuid4())], [dal['id']],
               [dal['id'], {}], [str(uuid4()) for _ in range(11)]]
    for ids in invalid:
        with pytest.raises(ApplicationError):
            await service.plan_combination(WEEK, ids, WEEK, 'dinner', 3)
        assert await service.get_meal_plan(WEEK) == before
    await food.archive_recipe(ready['id'])
    with pytest.raises(ApplicationError, match='not found'):
        await service.plan_combination(WEEK, [dal['id'], ready['id']], WEEK, 'dinner', 3)
    assert await service.get_meal_plan(WEEK) == before


@pytest.mark.asyncio
async def test_reusable_combination_uses_only_existing_library_food_and_preserves_sources():
    _, service, food, dal, _ = await example()
    ready = await food.save_recipe({'title': 'Ready rotis', 'kind': 'ready_food'})
    saved = await service.meals.save_combination([dal['id'], ready['id']], 4, 'Weeknight dinner')
    assert saved['name'] == 'Dal + Ready rotis'
    assert saved['notes'] == 'Weeknight dinner'
    assert [(row['recipeId'], row['quantity'], row['source']) for row in saved['components']] == [
        (dal['id'], 4, 'cook'), (ready['id'], 4, 'ready')]
    before = await service.meals.search()
    for ids in ([dal['id']], [dal['id'], dal['id']], [dal['id'], str(uuid4())], [dal['id'], {}]):
        with pytest.raises(ApplicationError):
            await service.meals.save_combination(ids, 4)
        assert await service.meals.search() == before
    await food.archive_recipe(ready['id'])
    with pytest.raises(ApplicationError, match='not found'):
        await service.meals.save_combination([dal['id'], ready['id']], 4)
    assert await service.meals.search() == before


@pytest.mark.asyncio
async def test_library_edits_archives_and_recipe_edits_preserve_planned_snapshots():
    repo, service, food, dal, meal = await example()
    plan = await service.plan_saved_meal(WEEK, meal['id'], WEEK, 'dinner')
    original = deepcopy(plan['entries'][0])
    updated = await service.meals.save({**meal, 'name': 'Updated dinner', 'components': [{**row, 'quantity': 1} for row in meal['components']]})
    assert updated['revision'] == 2
    await food.save_recipe({**dal, 'ingredients': [{'name': 'Lentils', 'quantity': 900, 'unit': 'g'}]})
    edited = await service.update_plan_item(WEEK, 'meal', {'id': original['id'], 'notes': 'Tuesday leftovers'})
    assert edited['entries'][0]['sourceMeal'] == original['sourceMeal']
    assert edited['entries'][0]['components'] == original['components']
    next_week = await service.plan_saved_meal('2030-02-11', meal['id'], '2030-02-11', 'dinner')
    assert next_week['entries'][0]['sourceMeal']['revision'] == 2
    assert next_week['entries'][0]['components'][1]['recipeSnapshot']['ingredients'][0]['quantity'] == 900
    archive = await service.meals.archive(meal['id'])
    assert archive['archivedAt']
    assert await service.meals.archive(meal['id']) == archive
    assert (await service.meals.search())['total'] == 0
    await service.update_plan_item(WEEK, 'meal', {'id': original['id'], 'notes': 'History can still be edited'})
    for op in (service.meals.save(updated), service.plan_saved_meal(WEEK, meal['id'], WEEK, 'dinner')):
        with pytest.raises(ApplicationError, match='Archived'):
            await op
    assert len((await service.get_meal_plan(WEEK))['entries']) == 1
    complete = await service.complete_item(WEEK, 'meal', original['id'])
    with pytest.raises(ApplicationError, match='Completed'):
        await service.update_plan_item(WEEK, 'meal', {'id': original['id'], 'meal': 'Changed after eating'})
    assert (await service.get_meal_plan(WEEK)) == complete['plan']
    assert repo._pantry == []


@pytest.mark.asyncio
async def test_searches_all_saved_meals_with_pagination_and_excludes_archived():
    repo = DemoRepository(); service = PlanningService(repo)
    oldest = await service.meals.save({'name': 'Old dinner', 'servings': 2, 'notes': 'After school', 'components': [{'name': 'Popcorn'}]})
    for index in range(55):
        await service.meals.save({'name': f'Dinner {index}', 'servings': 1, 'components': [{'name': 'Roti'}]})
    assert (await service.meals.search())['total'] == 56
    page = await service.meals.search(offset=50)
    assert len(page['items']) == 6 and page['items'][-1]['id'] == oldest['id']
    for query in ('POPCORN', 'school', 'old dinner'):
        assert (await service.meals.search(query))['items'] == [oldest]
    await service.meals.archive(oldest['id'])
    assert (await service.meals.search('popcorn'))['total'] == 0
    for query, limit, offset in [('', 0, 0), ('', 101, 0), ('', 10, -1), ('x' * 201, 50, 0), ('', True, 0)]:
        with pytest.raises(ApplicationError): await service.meals.search(query, limit, offset)


@pytest.mark.asyncio
async def test_invalid_library_updates_and_plan_targets_leave_existing_data_unchanged():
    repo, service, _, _, meal = await example()
    for changes in [{'name': ''}, {'servings': 0}, {'components': []},
                    {'components': [meal['components'][0], meal['components'][0]]},
                    {'components': [{'name': 'Missing', 'source': 'cook', 'recipeId': str(uuid4())}]},
                    {'components': [{'name': 'Batch', 'source': 'task', 'taskId': str(uuid4())}]},
                    {'components': [{'name': 'Lot', 'pantryItemId': str(uuid4())}]},
                    {'components': [{'name': 'Negative', 'quantity': -1}]}]:
        with pytest.raises(ApplicationError): await service.meals.save({**meal, **changes})
        assert await service.meals.get(meal['id']) == meal
    for date, slot, servings in [('2030-02-11', 'dinner', 4), (WEEK, 'prep', 4), (WEEK, 'dinner', -1)]:
        with pytest.raises(ApplicationError): await service.plan_saved_meal(WEEK, meal['id'], date, slot, servings)
        assert await service.get_meal_plan(WEEK) is None
    with pytest.raises(ApplicationError): await service.meals.get(str(uuid4()))
    with pytest.raises(ApplicationError): await service.save_planned_meal(WEEK, str(uuid4()))
    assert (await service.meals.search())['total'] == 1


@pytest.mark.asyncio
async def test_saving_from_plan_detaches_batch_and_stock_references_and_copies_completed_meals():
    _, service, food, dal, _ = await example()
    stock = await food.update_pantry_item({'name': 'Rotis', 'quantity': 10, 'unit': 'pieces'})
    task_id = str(uuid4())
    plan = await service.save_meal_plan({'weekStart': WEEK, 'tasks': [{'id': task_id, 'title': 'Cook dal', 'recipeId': dal['id'], 'servings': 8}],
        'entries': [{'date': WEEK, 'slot': 'dinner', 'meal': 'Use prepared dal', 'servings': 4, 'components': [
            {'name': 'Dal', 'quantity': 4, 'unit': 'servings', 'source': 'task', 'taskId': task_id},
            {'name': 'Rotis', 'quantity': 8, 'unit': 'pieces', 'pantryItemId': stock['id']}]}]})
    completed = await service.complete_item(WEEK, 'meal', plan['entries'][0]['id'])
    saved = await service.save_planned_meal(WEEK, plan['entries'][0]['id'])
    assert saved['components'][0]['source'] == 'cook' and saved['components'][0]['recipeId'] == dal['id']
    assert all(not row['pantryItemId'] and not row['taskId'] for row in saved['components'])
    assert (await service.get_meal_plan(WEEK)) == completed['plan']
    next_week = await service.plan_saved_meal('2030-02-11', saved['id'], '2030-02-11', 'dinner')
    assert not next_week['tasks']
    assert next_week['entries'][0]['components'][0]['recipeSnapshot']['title'] == 'Dal'
    assert not next_week['entries'][0]['completedAt']


@pytest.mark.asyncio
async def test_shared_library_types_component_links_ready_food_demand_and_receipt():
    repo, planning, food, dal, original = await example()
    rotis = await food.save_recipe({'title': 'Pre-cooked rotis', 'kind': 'ready_food', 'servings': 4,
                                   'instructions': ['Heat and serve'], 'tags': ['quick']})
    meal = await planning.meals.save({'name': 'Dal and bought rotis', 'servings': 4, 'components': [
        {'name': dal['title'], 'source': 'cook', 'recipeId': dal['id'], 'quantity': 4, 'unit': 'servings'},
        {'name': rotis['title'], 'source': 'ready', 'recipeId': rotis['id'], 'quantity': 8, 'unit': 'pieces', 'action': 'heat'}]})
    all_items = await food.browse_recipe_library(item_type='all')
    assert {dal['id'], rotis['id'], meal['id']} <= {r['id'] for r in all_items['items']}
    for kind, identifier in [('recipes', dal['id']), ('ready_food', rotis['id']), ('meals', meal['id'])]:
        rows = (await food.browse_recipe_library(query='rotis' if kind == 'ready_food' else '', item_type=kind))['items']
        assert identifier in {r['id'] for r in rows}
        if kind == 'recipes': assert rotis['id'] not in {r['id'] for r in rows}
    assert (await food.get_recipe(meal['components'][1]['recipeId']))['instructions'] == ['Heat and serve']
    share = await food.create_recipe_share(rotis['id'])
    copied = await food.copy_shared_recipe(share['token'])
    assert (await food.get_recipe(copied['recipeId']))['kind'] == 'ready_food'
    edited_ready = await food.save_recipe({**rotis, 'description':'Serve warm'})
    edited_ready.pop('kind')
    assert (await food.save_recipe(edited_ready))['kind'] == 'ready_food'
    filtered = await food.browse_recipe_library(filters={'tag': ['quick']}, item_type='meals')
    assert [r['id'] for r in filtered['items']] == [meal['id']]
    named = await food.browse_recipe_library(query='Dal and bought', item_type='meals')
    assert next(f for f in named['facets']['tag'] if f['label'] == 'quick')['count'] == 1
    first = await food.browse_recipe_library(item_type='all', limit=1)
    second = await food.browse_recipe_library(item_type='all', limit=1, offset=1)
    assert first['hasMore'] and first['items'][0]['id'] != second['items'][0]['id']
    await planning.plan_saved_meal(WEEK, meal['id'], WEEK, 'dinner', 8)
    demand = await planning.preview_shopping(WEEK)
    assert {r['name']: r['quantity'] for r in demand['items']} == {'Lentils': 400, rotis['title']: 16}
    from app.application.services import ShoppingService
    shopping = ShoppingService(repo)
    item = (await shopping.add_item({'name': rotis['title'], 'quantity': 16, 'unit': 'pieces'}))['items'][-1]
    received = await shopping.receive_item(item['id'], 16, 'pieces')
    assert received['pantryItem']['name'] == rotis['title']
    assert {r['name']: r['quantity'] for r in (await planning.preview_shopping(WEEK))['items']} == {'Lentils': 400}
    task_id = str(uuid4())
    batch_week = '2030-02-11'
    batch = await planning.save_meal_plan({'weekStart':batch_week, 'tasks':[{'id':task_id,'title':'Heat rotis','recipeId':rotis['id'],'servings':4}],
        'entries':[{'date':batch_week,'slot':'dinner','meal':'Heated rotis','servings':4,'components':[
            {'name':rotis['title'],'source':'task','action':'heat','taskId':task_id,'quantity':8,'unit':'pieces'}]}]})
    saved_batch = await planning.save_planned_meal(batch_week, batch['entries'][0]['id'])
    assert saved_batch['components'][0]['source'] == 'ready'
    assert saved_batch['components'][0]['recipeId'] == rotis['id']
    assert saved_batch['components'][0]['action'] == 'heat'
    for value in ({'title':'Invalid', 'kind':'meal'}, {'title':'Invalid', 'kind':'ready_food', 'ingredients':[{'name':'Flour'}]}):
        with pytest.raises(ApplicationError): await food.save_recipe(value)
    with pytest.raises(ApplicationError, match='Library type'):
        await food.browse_recipe_library(item_type='unknown')
    with pytest.raises(ApplicationError, match='ready component'):
        await planning.meals.save({**meal, 'components': [{**meal['components'][1], 'source':'cook'}]})
    assert await planning.meals.get(meal['id']) == meal
