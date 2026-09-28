import pytest

from app.application.errors import ApplicationError
from app.application.services import HouseholdService, PlanningService
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
