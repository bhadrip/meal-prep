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
