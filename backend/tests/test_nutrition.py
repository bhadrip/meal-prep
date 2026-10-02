from copy import deepcopy

import pytest

from app.application.errors import ApplicationError
from app.application.services import PlanningService, HouseholdService
from app.infrastructure.repositories import DemoRepository

WEEK = '2043-02-02'
GUIDE = {'basis': 'Ingredient-based estimate; portions unverified', 'profiles': [
    {'name': 'Standard', 'serving': 'Mild noodles', 'macros': {'protein': 'low', 'carbs': 'high'}},
    {'name': 'Protein-heavy', 'serving': 'Less noodles, add tofu and broccoli',
     'macros': {'protein': 'high', 'carbs': 'moderate'},
     'micronutrients': [{'nutrient': 'Iron', 'source': 'Tofu'}]},
]}


@pytest.mark.asyncio
async def test_nutrition_persists_unknowns_and_partial_edits_then_clears():
    service = PlanningService(DemoRepository())
    saved = await service.save_meal_plan({'weekStart': WEEK, 'entries': [
        {'date': WEEK, 'slot': 'dinner', 'meal': 'Teriyaki noodles', 'nutrition': GUIDE}]})
    entry = saved['entries'][0]
    assert entry['nutrition']['profiles'][0]['macros']['fat'] == 'unknown'
    assert entry['nutrition']['profiles'][1]['micronutrients'][0]['source'] == 'Tofu'
    edited = await service.update_plan_item(WEEK, 'meal', {'id': entry['id'], 'notes': 'Sauce separate'})
    assert edited['entries'][0]['nutrition'] == entry['nutrition']
    assert (await service.get_meal_plan(WEEK))['entries'][0]['nutrition'] == entry['nutrition']
    cleared = await service.update_plan_item(WEEK, 'meal', {'id': entry['id'], 'nutrition': None})
    assert cleared['entries'][0]['nutrition'] is None


@pytest.mark.asyncio
async def test_invalid_nutrition_never_replaces_saved_plan():
    service = PlanningService(DemoRepository())
    saved = await service.save_meal_plan({'weekStart': WEEK, 'entries': [
        {'date': WEEK, 'slot': 'dinner', 'meal': 'Noodles', 'nutrition': GUIDE}]})
    invalid = [[], {'basis': '', 'profiles': GUIDE['profiles']}, {'basis': 'Guess', 'profiles': []}]
    for profile in [ {'name': 'Adult', 'serving': 'Tofu', 'macros': {'protein': 50}},
                     {'name': 'Adult', 'serving': 'Tofu', 'macros': {'sodium': 'high'}},
                     {'name': 'Adult', 'serving': 'Tofu', 'micronutrients': [{'nutrient': 'Iron'}]}]:
        invalid.append({'basis': 'Estimate', 'profiles': [profile]})
    invalid.append({'basis': 'Estimate', 'profiles': [GUIDE['profiles'][0]] * 2})
    invalid.append({'basis': 'Estimate', 'profiles': [GUIDE['profiles'][0]] * 9})
    for nutrition in invalid:
        with pytest.raises(ApplicationError):
            await service.update_plan_item(WEEK, 'meal', {'id': saved['entries'][0]['id'], 'nutrition': nutrition})
        assert await service.get_meal_plan(WEEK) == saved


@pytest.mark.asyncio
async def test_numeric_nutrients_keep_units_zero_unknowns_and_portion():
    service = PlanningService(DemoRepository())
    guide = deepcopy(GUIDE)
    guide['profiles'][1].update(portion='1 protein-heavy bowl', valueType='estimated',
        amounts={'calories': 520, 'protein': 35.5, 'carbs': 48, 'fat': 0})
    guide['profiles'][1]['micronutrients'][0].update(amount=3.2, unit='mg')
    saved = await service.save_meal_plan({'weekStart': WEEK, 'entries': [
        {'date': WEEK, 'slot': 'dinner', 'meal': 'Noodles', 'nutrition': guide}]})
    profile = saved['entries'][0]['nutrition']['profiles'][1]
    assert profile['amounts'] == {'calories': 520, 'protein': 35.5, 'carbs': 48, 'fat': 0, 'fiber': None}
    assert profile['micronutrients'][0]['amount'] == 3.2
    assert profile['micronutrients'][0]['unit'] == 'mg'
    edited = await service.update_plan_item(WEEK, 'meal', {'id': saved['entries'][0]['id'], 'notes': 'Keep portion'})
    assert edited['entries'][0]['nutrition'] == saved['entries'][0]['nutrition']
    for change in [{'portion': ''}, {'valueType': 'exact'}, {'amounts': {'protein': -1}},
                   {'amounts': {'protein': True}}, {'amounts': {'protein': '35'}},
                   {'amounts': {'protein': float('nan')}}, {'amounts': {'protein': float('inf')}},
                   {'amounts': {'protein': 1.2345}}, {'amounts': {'protein': 1000001}},
                   {'amounts': {'sodium': 300}},
                   {'micronutrients': [{'nutrient': 'Iron', 'source': 'Tofu', 'amount': 3, 'unit': 'kcal'}]},
                   {'micronutrients': [{'nutrient': 'Iron', 'source': 'Tofu', 'unit': 'mg'}]}]:
        invalid = deepcopy(edited['entries'][0]['nutrition'])
        invalid['profiles'][1].update(change)
        with pytest.raises(ApplicationError):
            await service.update_plan_item(WEEK, 'meal', {'id': saved['entries'][0]['id'], 'nutrition': invalid})
        assert await service.get_meal_plan(WEEK) == edited
    label = deepcopy(edited['entries'][0]['nutrition'])
    label['profiles'][1]['valueType'] = 'label'
    assert (await service.update_plan_item(WEEK, 'meal', {'id': saved['entries'][0]['id'], 'nutrition': label}))['entries'][0]['nutrition']['profiles'][1]['valueType'] == 'label'


@pytest.mark.asyncio
async def test_recipe_nutrition_persists_partial_edits_and_rejects_invalid_values():
    from app.application.services import RecipePantryService
    service = RecipePantryService(DemoRepository())
    guide = deepcopy(GUIDE)
    guide['profiles'][0].update(portion='1 serving', amounts={'protein': 20, 'fat': 0})
    recipe = await service.save_recipe({'title': 'Tofu noodles', 'nutrition': guide})
    assert (await service.get_recipe(recipe['id']))['nutrition'] == recipe['nutrition']
    updated = await service.save_recipe({'id': recipe['id'], 'title': 'Tofu noodles revised'})
    assert updated['nutrition'] == recipe['nutrition']
    invalid = deepcopy(guide)
    invalid['profiles'][0]['amounts']['protein'] = -20
    with pytest.raises(ApplicationError, match='nonnegative'):
        await service.save_recipe({'id': recipe['id'], 'title': 'Invalid edit', 'nutrition': invalid})
    assert (await service.get_recipe(recipe['id']))['title'] == updated['title']
    assert (await service.get_recipe(recipe['id']))['nutrition'] == updated['nutrition']
    assert (await service.save_recipe({'id': recipe['id'], 'title': updated['title'], 'nutrition': None}))['nutrition'] is None


@pytest.mark.asyncio
async def test_weekly_numbers_cover_one_plate_per_meal_and_keep_missing_values_unknown():
    service = PlanningService(DemoRepository())
    entries = []
    for index, protein in enumerate([30, 0, None]):
        guide = None
        if protein is not None:
            guide = {'basis': 'Estimate', 'profiles': [{'name': 'Protein-heavy' if index == 0 else 'protein-heavy',
                'serving': 'Tofu bowl', 'portion': '1 bowl', 'amounts': {'protein': protein, 'fat': 0},
                'micronutrients': [{'nutrient': 'Iron', 'source': 'Tofu', 'amount': 3 if index == 0 else 1000,
                                   'unit': 'mg' if index == 0 else 'mcg'}]}]}
        entries.append({'date': f'2043-02-0{2+index}', 'slot': 'dinner', 'meal': 'Noodles', 'nutrition': guide})
    await service.save_meal_plan({'weekStart': WEEK, 'entries': entries})
    summary = await service.get_weekly_nutrition(WEEK)
    assert summary['mealCount'] == 3
    assert len(summary['profiles']) == 1
    adult = summary['profiles'][0]
    assert adult['plannedPlates'] == 2
    assert adult['amounts']['protein'] == {'total': 30, 'coveredMeals': 2}
    assert adult['amounts']['fat'] == {'total': 0, 'coveredMeals': 2}
    assert adult['amounts']['calories'] == {'total': None, 'coveredMeals': 0}
    assert adult['micronutrients'] == [{'nutrient': 'Iron', 'unit': 'mg', 'total': 4, 'coveredMeals': 2}]
    with pytest.raises(ApplicationError, match='Monday'):
        await service.get_weekly_nutrition('2043-02-03')
    assert await service.get_weekly_nutrition(WEEK) == summary
    assert await service.get_weekly_nutrition('2043-02-09') == {'mealCount': 0, 'profiles': [], 'basis': summary['basis']}
    snapshot = await HouseholdService(service.repository).snapshot(sections=['mealPlan'], week_start=WEEK)
    assert snapshot['sections']['mealPlan']['value']['nutritionSummary'] == summary


@pytest.mark.asyncio
async def test_preparation_variations_are_freeform_and_rename_without_losing_numbers():
    service = PlanningService(DemoRepository())
    guide = {'basis': 'Ingredient estimate', 'profiles': [
        {'name': 'Standard', 'serving': 'Original plate', 'portion': '1 bowl', 'amounts': {'protein': 15}},
        {'name': 'Protein-heavy', 'serving': 'Add tofu', 'portion': '1 bowl', 'amounts': {'protein': 35}}]}
    saved = await service.save_meal_plan({'weekStart': WEEK, 'entries': [
        {'date': WEEK, 'slot': 'dinner', 'meal': 'Noodles', 'nutrition': guide}]})
    renamed = deepcopy(saved['entries'][0]['nutrition'])
    renamed['profiles'][0]['name'] = 'Quick'
    await service.update_plan_item(WEEK, 'meal', {'id': saved['entries'][0]['id'], 'nutrition': renamed})
    profiles = (await service.get_weekly_nutrition(WEEK))['profiles']
    assert [(p['name'], p['amounts']['protein']['total']) for p in profiles] == [('Quick', 15), ('Protein-heavy', 35)]
    invalid = deepcopy(renamed)
    invalid['profiles'][0]['name'] = 'protein-heavy'
    with pytest.raises(ApplicationError, match='unique'):
        await service.update_plan_item(WEEK, 'meal', {'id': saved['entries'][0]['id'], 'nutrition': invalid})
    assert (await service.get_weekly_nutrition(WEEK))['profiles'] == profiles
