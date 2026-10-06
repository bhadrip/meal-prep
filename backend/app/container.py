"""Application composition for one authenticated request."""

from .application import (
    FeedbackService,
    HouseholdService,
    MealPrepServices,
    MemoryService,
    PlanningService,
    RecipePantryService,
    ShoppingService,
    CircleService,
)
from .analytics import analytics_for_request
from .infrastructure.repositories import repository_for_request


def services_for_request(access_token: str | None = None, user_id: str | None = None) -> MealPrepServices:
    """Compose services for MCP context or an explicit HTTP bearer token."""
    repository = repository_for_request(access_token)
    analytics = analytics_for_request(user_id)
    return MealPrepServices(
        household=HouseholdService(repository, analytics),
        food=RecipePantryService(repository),
        planning=PlanningService(repository, analytics),
        feedback=FeedbackService(repository, analytics),
        memory=MemoryService(repository, analytics),
        shopping=ShoppingService(repository, analytics),
        circles=CircleService(repository),
    )
