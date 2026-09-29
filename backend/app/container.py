"""Application composition for one authenticated request."""

from .application import (
    FeedbackService,
    HouseholdService,
    MealPrepServices,
    MemoryService,
    PlanningService,
    RecipePantryService,
    ShoppingService,
)
from .infrastructure.repositories import repository_for_request


def services_for_request() -> MealPrepServices:
    repository = repository_for_request()
    return MealPrepServices(
        household=HouseholdService(repository),
        food=RecipePantryService(repository),
        planning=PlanningService(repository),
        feedback=FeedbackService(repository),
        memory=MemoryService(repository),
        shopping=ShoppingService(repository),
    )
