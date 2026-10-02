from uuid import uuid4

import pytest

from app.application.errors import ApplicationError
from app.application.services import HouseholdService, PlanningService, RecipePantryService, ShoppingService
from app.infrastructure.repositories import DemoRepository

WEEK = "2030-02-04"


async def example():
    repo = DemoRepository()
    repo._pantry = []
    repo._shopping_list = {"id": str(uuid4()), "name": "Groceries", "items": []}
    food = RecipePantryService(repo)
    stocks = {}
    for name, quantity, unit in [("Rotis", 12, "pieces"), ("Lentils", 250, "g"), ("Yogurt", 300, "g")]:
        stocks[name] = await food.update_pantry_item({"name": name, "quantity": quantity, "unit": unit, "quantityConfidence": "exact"})
    recipe = await food.save_recipe({"title": "Dal", "servings": 4, "ingredients": [{"name": "Lentils", "quantity": 200, "unit": "g"}]})
    task_id = str(uuid4())
    plan = {"weekStart": WEEK, "entries": [], "tasks": [{"id": task_id, "date": "2030-02-03", "title": "Cook dal once",
        "recipeId": recipe["id"], "servings": 8}, {"title": "Pack snacks", "notes": "Kids and parents", "date": None}]}
    for date in [WEEK, "2030-02-05"]:
        plan["entries"].append({"date": date, "slot": "dinner", "meal": f"Roti dinner {date}", "servings": 4,
            "components": [{"name": "Rotis", "quantity": 8, "unit": "pieces", "source": "ready", "action": "heat", "pantryItemId": stocks["Rotis"]["id"]},
                           {"name": "Dal", "quantity": 4, "unit": "servings", "source": "task", "taskId": task_id},
                           {"name": "Yogurt", "quantity": 200, "unit": "g", "source": "ready"}]})
    service = PlanningService(repo)
    return repo, service, stocks, recipe, await service.save_meal_plan(plan)


@pytest.mark.asyncio
async def test_slots_are_ordered_stable_and_disabled_slots_preserve_existing_meals():
    repo, service, _, _, saved = await example()
    household = HouseholdService(repo)
    slots = (await household.get_context())["mealSlots"]
    slots = [{"id": "kids-am", "name": "Kids snack AM", "enabled": True}, *slots]
    updated = await household.configure_meal_slots(slots)
    assert updated["planningPreferences"]["weeknightMaxMinutes"] == 30
    meal_id = saved["entries"][0]["id"]
    await service.update_plan_item(WEEK, "meal", {"id": meal_id, "slot": "kids-am"})
    slots[0] = {**slots[0], "name": "School snack", "enabled": False}
    updated = await household.configure_meal_slots(list(reversed(slots)))
    assert updated["mealSlots"][-1]["id"] == "kids-am"
    edited = await service.update_plan_item(WEEK, "meal", {"id": meal_id, "notes": "Pack separately"})
    assert edited["entries"][0]["id"] == meal_id and edited["entries"][0]["slotName"] == "School snack"
    with pytest.raises(ApplicationError, match="enabled"):
        await service.update_plan_item(WEEK, "meal", {"date": WEEK, "slot": "kids-am", "meal": "New snack"})
    for invalid in [slots + [slots[0]], [{**row, "enabled": False} for row in slots], slots[1:]]:
        with pytest.raises(ApplicationError):
            await household.configure_meal_slots(invalid)
    assert (await household.get_context())["mealSlots"] == updated["mealSlots"]


@pytest.mark.asyncio
async def test_mixed_meals_batch_demand_and_shopping_regeneration_do_not_consume_stock():
    repo, service, stocks, recipe, saved = await example()
    before = await repo.get_pantry()
    preview = await service.preview_shopping(WEEK)
    assert {row["name"]: row["quantity"] for row in preview["items"]} == {"Rotis": 4, "Lentils": 150, "Yogurt": 100}
    assert preview["warnings"] == []
    assert len(next(row for row in preview["items"] if row["name"] == "Rotis")["source"]["reasons"]) == 2
    assert await repo.get_pantry() == before
    await ShoppingService(repo).add_item({"name": "Soap", "quantity": 1, "unit": "bottle"})
    generated = await service.save_plan_shopping(WEEK)
    manual_id = next(row["id"] for row in generated["shoppingList"]["items"] if row["name"] == "Soap")
    assert len(generated["shoppingList"]["items"]) == 4
    assert len((await service.save_plan_shopping(WEEK))["shoppingList"]["items"]) == 4
    assert (await repo.get_shopping_list())["items"][0]["id"] == manual_id
    # Recipe edits do not silently change the ingredient quantities already agreed for this plan.
    await RecipePantryService(repo).save_recipe({**recipe, "ingredients": [{"name": "Lentils", "quantity": 900, "unit": "g"}]})
    await service.update_plan_item(WEEK, "task", {"id": saved["tasks"][1]["id"], "notes": "Pack tonight"})
    assert next(row["quantity"] for row in (await service.preview_shopping(WEEK))["items"] if row["name"] == "Lentils") == 150


@pytest.mark.asyncio
async def test_invalid_references_dates_and_portions_do_not_replace_the_plan():
    repo, service, stocks, recipe, saved = await example()
    for changes in [{"slot": "prep"}, {"date": "2030-02-11"}, {"components": [{"name": "Bad food", "pantryItemId": str(uuid4())}]},
                    {"components": [{"name": "Dal", "source": "cook", "recipeId": str(uuid4())}]},
                    {"components": [{"name": "Dal", "source": "task", "taskId": str(uuid4())}]},
                    {"components": [{"name": "Dal", "quantity": -1}]}]:
        with pytest.raises(ApplicationError):
            await service.update_plan_item(WEEK, "meal", {"id": saved["entries"][0]["id"], **changes})
        assert await service.get_meal_plan(WEEK) == saved
    with pytest.raises(ApplicationError, match="after the meal"):
        await service.update_plan_item(WEEK, "task", {"id": saved["tasks"][0]["id"], "date": "2030-02-06"})
    with pytest.raises(ApplicationError, match="unique"):
        await service.save_meal_plan({**saved, "tasks": saved["tasks"] + [saved["tasks"][0]]})
    await service.update_plan_item(WEEK, "task", {"id": saved["tasks"][0]["id"], "servings": 7})
    assert any("8" in warning and "7" in warning for warning in (await service.preview_shopping(WEEK))["warnings"])


@pytest.mark.asyncio
async def test_actual_cooking_eating_and_receipts_are_atomic_and_safe_to_retry():
    repo, service, stocks, _, plan = await example()
    task_id = plan["tasks"][0]["id"]
    before = await repo.get_pantry()
    with pytest.raises(ApplicationError, match="Not enough"):
        await service.complete_item(WEEK, "task", task_id, [{"itemId": stocks["Lentils"]["id"], "quantity": 400}],
                                    [{"name": "Dal", "quantity": 8, "unit": "servings"}])
    assert await repo.get_pantry() == before and not (await service.get_meal_plan(WEEK))["tasks"][0]["completedAt"]
    cooked = await service.complete_item(WEEK, "task", task_id, [{"itemId": stocks["Lentils"]["id"], "quantity": 200}],
                                         [{"name": "Dal", "quantity": 7, "unit": "servings"}])
    after = await repo.get_pantry()
    assert await service.complete_item(WEEK, "task", task_id) == cooked
    assert await repo.get_pantry() == after
    dal_id = cooked["activity"]["outputs"][0]["itemId"]
    await service.complete_item(WEEK, "meal", plan["entries"][0]["id"], [{"itemId": dal_id, "quantity": 4}])
    assert next(row["quantity"] for row in await repo.get_pantry() if row["id"] == dal_id) == 3
    assert next(row["quantity"] for row in (await service.preview_shopping(WEEK))["items"] if row["name"] == "Dal") == 1
    with pytest.raises(ApplicationError, match="Completed"):
        await service.update_plan_item(WEEK, "meal", {"id": plan["entries"][0]["id"], "meal": "Rewrite history"})
    # An unrelated future task is editable after cooking completes.
    await service.update_plan_item(WEEK, "task", {"id": plan["tasks"][1]["id"], "notes": "Tomorrow"})
    check = await service.complete_item(WEEK, "task", plan["tasks"][1]["id"])
    assert check["activity"]["inputs"] == [] and check["activity"]["outputs"] == []
    shopping = ShoppingService(repo)
    line = (await shopping.add_item({"name": "Rotis", "quantity": 1, "unit": "pack"}))["items"][-1]
    stock_before = await repo.get_pantry()
    await shopping.mark_purchased(line["id"], True)
    assert await repo.get_pantry() == stock_before
    receipt = await shopping.receive_item(line["id"], 20, "pieces")
    assert receipt["pantryItem"]["quantity"] == 20
    assert await shopping.receive_item(line["id"], 20, "pieces") == receipt
    assert len(await repo.get_pantry()) == len(stock_before) + 1
    with pytest.raises(ApplicationError):
        await shopping.receive_item(line["id"], -1, "pieces")


@pytest.mark.asyncio
async def test_uncertain_stock_missing_units_and_takeout_are_explicit():
    repo, service, stocks, _, saved = await example()
    await RecipePantryService(repo).update_pantry_item({"id": stocks["Rotis"]["id"], "quantityConfidence": "unknown"})
    await service.update_plan_item(WEEK, "meal", {"date": "2030-02-06", "slot": "snack", "meal": "Popcorn",
        "components": [{"name": "Popcorn"}]})
    await service.update_plan_item(WEEK, "meal", {"date": "2030-02-07", "slot": "dinner", "meal": "Restaurant",
        "components": [{"name": "Takeout pizza", "source": "external"}]})
    preview = await service.preview_shopping(WEEK)
    assert next(row["quantity"] for row in preview["items"] if row["name"] == "Rotis") == 16
    assert any("Check pantry quantity" in warning for warning in preview["warnings"])
    assert any("Popcorn" in warning for warning in preview["warnings"])
    assert not any(row["name"] == "Takeout pizza" for row in preview["items"])
