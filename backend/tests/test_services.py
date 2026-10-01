from unittest.mock import AsyncMock

import pytest

from app.application.errors import ApplicationError, RepositoryError, StorageNotInstalledError
from app.application.services import (
    FeedbackService,
    HouseholdService,
    PlanningService,
    RecipePantryService,
    ShoppingService,
)
from app.infrastructure.repositories import DemoRepository


@pytest.mark.asyncio
async def test_recipe_tags_are_normalized_and_filter_exactly():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    sick = await service.save_recipe({"title": "Ginger soup", "tags": [" Sickness-Friendly ", "sickness-friendly", "guest-friendly"]})
    await service.save_recipe({"title": "Party soup", "tags": ["guest-friendly"]})
    assert sick["tags"] == ["sickness-friendly", "guest-friendly"]
    assert [item["title"] for item in await service.search_recipes(tag="SICKNESS-FRIENDLY")] == ["Ginger soup"]
    assert [item["title"] for item in await service.search_recipes(query="sickness-friendly")] == ["Ginger soup"]
    assert [item["title"] for item in await service.search_recipes(query="sick")] == ["Ginger soup"]
    assert await service.search_recipes(tag="sickness") == []
    assert await service.list_recipe_tags() == [
        {"tag": "guest-friendly", "recipe_count": 2},
        {"tag": "sickness-friendly", "recipe_count": 1},
    ]
    assert await service.search_recipes(query="invented-tag") == []
    with pytest.raises(ApplicationError, match="recipe tags must be nonempty"):
        await service.save_recipe({"title": "Invalid", "tags": [" "]})
    assert await service.search_recipes(query="Invalid") == []


@pytest.mark.asyncio
async def test_pantry_categories_classify_clear_items_and_reject_invalid_choice():
    service = RecipePantryService(DemoRepository())
    examples = [
        ("Apples", "pantry", "fruits"),
        ("Baby spinach", "fridge", "vegetables"),
        ("Popcorn", "pantry", "snacks"),
        ("Peas", "freezer", "frozen"),
        ("Rice", "pantry", "dry_goods"),
        ("Garlic paste", "fridge", "condiments"),
        ("Mystery tin", "pantry", "uncategorized"),
    ]
    for name, location, category in examples:
        saved = await service.update_pantry_item({"name": name, "storageLocation": location})
        assert saved["category"] == category
    with pytest.raises(ApplicationError, match="Invalid pantry category"):
        await service.update_pantry_item({"name": "Apples", "category": "unknown-category"})


@pytest.mark.asyncio
async def test_recipe_detail_survives_missing_feedback_storage():
    repository = DemoRepository()
    repository.get_recipe = AsyncMock(return_value={"id": "recipe-1", "title": "Lentil soup"})
    repository.get_feedback = AsyncMock(side_effect=StorageNotInstalledError("feedback"))

    recipe = await RecipePantryService(repository).get_recipe("recipe-1")

    assert recipe == {
        "id": "recipe-1",
        "title": "Lentil soup",
        "feedback": [],
        "feedbackUnavailable": True,
    }
    repository.get_feedback.assert_awaited_once_with(recipe_id="recipe-1", limit=25)

    repository.get_feedback.side_effect = RepositoryError("Database unavailable")
    with pytest.raises(RepositoryError, match="Database unavailable"):
        await RecipePantryService(repository).get_recipe("recipe-1")


@pytest.mark.asyncio
async def test_record_pantry_use_subtracts_and_links_recipe():
    repository = DemoRepository()
    service = RecipePantryService(repository)
    item = (await service.get_pantry())[0]
    use = await service.record_pantry_use(
        item["id"], 0.25, "11111111-1111-1111-1111-111111111111", "Tuesday dinner",
    )
    assert use["quantityBefore"] == 1
    assert use["quantityRemaining"] == 0.75
    assert use["recipeTitle"] == "Paneer rice bowls"
    assert use["mealTitle"] == "Tuesday dinner"
    assert (await service.get_pantry())[0]["quantity"] == 0.75
    assert (await service.get_pantry())[0]["reference_quantity"] == 1

    with pytest.raises(ApplicationError, match="exceeds"):
        await service.record_pantry_use(item["id"], 1)
    with pytest.raises(ApplicationError, match="positive"):
        await service.record_pantry_use(item["id"], -1)
    with pytest.raises(ApplicationError, match="Recipe was not found"):
        await service.record_pantry_use(item["id"], 0.1, "missing")
    assert (await service.get_pantry())[0]["quantity"] == 0.75


@pytest.mark.asyncio
async def test_household_service_owns_onboarding_rules():
    service = HouseholdService(DemoRepository())

    with pytest.raises(ApplicationError, match="dietary_restrictions"):
        await service.update_preferences(household_size=2, complete_onboarding=True)


@pytest.mark.asyncio
async def test_household_service_rejects_invalid_dashboard_cards():
    service = HouseholdService(DemoRepository())

    with pytest.raises(ApplicationError, match="Unknown dashboard card IDs"):
        await service.configure_dashboard(card_order=["shopping-list", "weather"])
    with pytest.raises(ApplicationError, match="duplicate"):
        await service.configure_dashboard(card_order=["pantry", "pantry"])


@pytest.mark.asyncio
async def test_planning_service_requires_an_explicit_slot_for_every_entry():
    service = PlanningService(DemoRepository())
    plan = {
        "weekStart": "2026-09-28",
        "entries": [{"day": "Monday", "meal": "Vegetable pasta"}],
    }

    with pytest.raises(ApplicationError, match="meal slot"):
        await service.save_meal_plan(plan)

    plan["entries"][0]["slot"] = "dinner"
    saved = await service.save_meal_plan(plan)
    assert saved["entries"][0]["slot"] == "dinner"


@pytest.mark.asyncio
async def test_demo_plan_keeps_each_week_and_returns_the_latest_week():
    repository = DemoRepository()
    first_week = await repository.get_meal_plan()
    next_week = "2030-02-04"
    saved = await PlanningService(repository).save_meal_plan({
        "weekStart": next_week,
        "entries": [{"date": next_week, "slot": "dinner", "meal": "Lentil bowls"}],
    })

    assert (await repository.get_meal_plan(first_week["weekStart"]))["id"] == first_week["id"]
    assert (await repository.get_meal_plan(next_week))["id"] == saved["id"]
    assert (await repository.get_meal_plan())["weekStart"] == next_week


@pytest.mark.asyncio
async def test_shopping_item_store_is_optional_and_does_not_replace_list():
    service = ShoppingService(DemoRepository())
    original = await service.get()
    tagged = await service.add_item({"name": "  Milk  ", "store": "  Trader Joe's  ", "quantity": 1})
    assert len(tagged["items"]) == len(original["items"]) + 1
    assert tagged["items"][-1]["name"] == "Milk"
    assert tagged["items"][-1]["store"] == "Trader Joe's"

    untagged = await service.add_item({"name": "Bread", "store": "   "}, tagged["id"])
    assert untagged["items"][-1]["store"] is None
    assert untagged["items"][-2]["store"] == "Trader Joe's"

    with pytest.raises(ApplicationError, match="item.name"):
        await service.add_item({"name": " "})


@pytest.mark.asyncio
async def test_feedback_service_requires_a_subject_and_normalizes_tags():
    service = FeedbackService(DemoRepository())

    with pytest.raises(ApplicationError, match="must identify"):
        await service.save({"note": "Too salty"})
    with pytest.raises(ApplicationError, match="not both"):
        await service.save(
            {
                "note": "Duplicate subject",
                "occurrenceId": "one",
                "mealPlanEntryId": "two",
            }
        )

    saved = await service.save(
        {
            "recipeId": "11111111-1111-1111-1111-111111111111",
            "note": " Sauce was too salty. ",
            "nextTime": "Use half the soy sauce.",
            "tags": ["Too-Salty", "kids", "too-salty"],
            "rating": 3,
        }
    )

    assert saved["note"] == "Sauce was too salty."
    assert {tag["slug"] for tag in saved["tags"]} == {
        "too-salty", "family:kids", "change-next-time"
    }
    assert saved["occurrence"]["recipe_id"] == "11111111-1111-1111-1111-111111111111"
    updated = await service.save(
        {
            "id": saved["id"],
            "recipeId": "11111111-1111-1111-1111-111111111111",
            "note": "The sauce needed less salt.",
            "tags": ["too-salty"],
        }
    )
    assert updated["occurrence_id"] == saved["occurrence_id"]


@pytest.mark.asyncio
async def test_feedback_service_answers_what_worked_and_recipe_feedback_summary():
    service = FeedbackService(DemoRepository())
    recipe_id = "11111111-1111-1111-1111-111111111111"
    saved = await service.save(
        {
            "recipeId": recipe_id,
            "weekStart": "2026-09-28",
            "note": "The mild bowl worked for everyone.",
            "tags": ["very good", "kids", "easy cleanup"],
            "variantName": "Family mild",
            "adaptations": ["Serve chili oil at the table"],
        }
    )

    assert saved["feedback_type"] == "worked_well"
    assert saved["occurrence"]["variant"]["name"] == "Family mild"
    worked = await service.what_worked(tags=["worked well"])
    assert any(item["id"] == saved["id"] for item in worked["items"])
    summary = await service.recipe_feedback_summary(recipe_id)
    assert summary["evidenceCount"] >= 1
    assert any(variant["name"] == "Family mild" for variant in summary["variants"])


@pytest.mark.asyncio
async def test_feedback_service_treats_a_preference_as_a_signal():
    service = FeedbackService(DemoRepository())

    saved = await service.save(
        {
            "weekStart": "2026-09-28",
            "note": "We prefer lighter dinners on Wednesdays.",
            "feedbackType": "preference",
        }
    )

    assert saved["feedback_type"] == "preference_signal"
    assert {tag["slug"] for tag in saved["tags"]} == {"preference-signal"}
    legacy_filter = await service.list(feedback_type="preference")
    assert any(item["id"] == saved["id"] for item in legacy_filter)


@pytest.mark.asyncio
async def test_pantry_partial_quantity_edit_preserves_evidence_and_rejects_invalid_values():
    service = RecipePantryService(DemoRepository())
    saved = await service.update_pantry_item({"name": "Mushrooms", "quantity": 2, "unit": "boxes", "storageLocation": "fridge",
                                             "acquiredAt": "2026-09-24", "freshnessBasis": "Receipt", "useByDate": "2026-10-03"})
    updated = await service.update_pantry_item({"id": saved["id"], "quantity": 0.5})
    assert updated["name"] == "Mushrooms"
    assert updated["acquiredAt"] == "2026-09-24"
    assert updated["freshnessBasis"] == "Receipt"
    assert updated["useByDate"] == "2026-10-03"
    assert updated["storageLocation"] == "fridge"
    assert updated["reference_quantity"] == 2
    for bad in (-1, "nan", "infinity", 0.0001, "oops"):
        with pytest.raises(ApplicationError, match="quantity must"):
            await service.update_pantry_item({"id": saved["id"], "quantity": bad})
    with pytest.raises(ApplicationError, match="not found"):
        await service.update_pantry_item({"id": "missing", "quantity": 1})
    with pytest.raises(ApplicationError, match="valid date"):
        await service.update_pantry_item({"id": saved["id"], "acquiredAt": "2026-02-30"})
    assert next(row for row in await service.get_pantry() if row["id"] == saved["id"])["quantity"] == 0.5


def test_pantry_freshness_uses_purchase_evidence_without_inventing_expiry():
    from datetime import date
    from app.application.pantry_freshness import pantry_freshness
    today = date(2026, 10, 1)
    item = {"name": "Mushrooms", "category": "uncategorized", "quantity": 1, "storage_location": "fridge",
            "freshness_basis": "Purchased 2026-09-24 at Costco", "created_at": "2026-09-01"}
    result = pantry_freshness(item, today)
    assert result["ageDays"] == 7
    assert result["status"] == "review_age"
    assert result["useByDate"] is None
    assert result["source"] == "Purchase date from receipt evidence"
    assert pantry_freshness({**item, "quantity": 0}, today)["status"] == "finished"
    assert pantry_freshness({**item, "storage_location": "freezer"}, today)["status"] == "undated"
    for evidence in (None, "Purchased 2026-02-30", "Purchased 2026-10-02", "Uploaded 2026-09-24"):
        unknown = pantry_freshness({**item, "freshness_basis": evidence}, today)
        assert unknown["ageDays"] is None
        assert unknown["status"] == "age_unknown"
    assert pantry_freshness({**item, "use_by_date": "2026-09-30"}, today)["status"] == "past_date"
    assert pantry_freshness({**item, "use_by_date": "2026-10-02"}, today)["daysUntilUseBy"] == 1


@pytest.mark.asyncio
async def test_snapshot_and_pantry_service_share_freshness():
    repository = DemoRepository()
    repository._pantry = [{"id": "mushroom", "name": "Mushrooms", "quantity": 1, "acquiredAt": "2020-01-01"}]
    direct = await RecipePantryService(repository).get_pantry()
    snapshot = await HouseholdService(repository).snapshot(sections=["pantry"])
    assert snapshot["sections"]["pantry"]["value"] == direct
    assert direct[0]["freshness"]["status"] == "review_age"


@pytest.mark.asyncio
async def test_finished_pantry_is_retained_and_restock_resets_tracked_amount():
    service = RecipePantryService(DemoRepository())
    item = await service.update_pantry_item({"name": "Raspberries", "quantity": 1, "unit": "package", "acquiredAt": "2020-01-01"})
    await service.record_pantry_use(item["id"], 1)
    finished = next(row for row in await service.get_pantry() if row["id"] == item["id"])
    assert finished["quantity"] == 0
    assert finished["freshness"]["status"] == "finished"
    with pytest.raises(ApplicationError, match="exceeds"):
        await service.record_pantry_use(item["id"], 1)
    restocked = await service.update_pantry_item({"id": item["id"], "quantity": 3, "acquiredAt": "2026-10-01"})
    assert restocked["reference_quantity"] == 3
    assert restocked["acquiredAt"] == "2026-10-01"
    assert len([row for row in await service.get_pantry() if row["id"] == item["id"]]) == 1
