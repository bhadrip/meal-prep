import pytest

from app.application.errors import ApplicationError
from app.application.services import FeedbackService, HouseholdService, PlanningService
from app.infrastructure.repositories import DemoRepository


@pytest.mark.asyncio
async def test_household_service_owns_onboarding_rules():
    service = HouseholdService(DemoRepository())

    with pytest.raises(ApplicationError, match="dietary_restrictions"):
        await service.update_preferences(household_size=2, complete_onboarding=True)


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
async def test_feedback_service_answers_what_worked_and_recipe_lessons():
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
    lessons = await service.recipe_lessons(recipe_id)
    assert lessons["evidenceCount"] >= 1
    assert any(variant["name"] == "Family mild" for variant in lessons["variants"])
