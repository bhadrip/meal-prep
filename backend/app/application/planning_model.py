"""Small, shared contracts for household slots, meal components, and tasks."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from .errors import ApplicationError

DEFAULT_MEAL_SLOTS = [
    {"id": "breakfast", "name": "Breakfast", "enabled": True},
    {"id": "lunch", "name": "Lunch", "enabled": True},
    {"id": "snack", "name": "Snack", "enabled": True},
    {"id": "dinner", "name": "Dinner", "enabled": True},
]


def meal_slots(household: dict) -> list[dict]:
    return deepcopy((household.get("planningPreferences") or {}).get("mealSlots", DEFAULT_MEAL_SLOTS))


def validate_slots(slots: list, previous: list) -> list[dict]:
    if not isinstance(slots, list) or not 1 <= len(slots) <= 24:
        raise ApplicationError("Provide between 1 and 24 meal slots")
    result, ids, names = [], set(), set()
    for slot in slots:
        if not isinstance(slot, dict):
            raise ApplicationError("Each meal slot must be an object")
        slot_id = text(slot.get("id"), "Slot ID", 80)
        if not all(c.isascii() and (c.isalnum() or c in "-_") for c in slot_id):
            raise ApplicationError("Slot IDs may contain letters, numbers, hyphens, and underscores")
        name = text(slot.get("name"), "Slot name", 80)
        enabled = slot.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ApplicationError("Slot enabled must be true or false")
        if slot_id in ids or name.casefold() in names:
            raise ApplicationError("Meal slot IDs and names must be unique")
        ids.add(slot_id)
        names.add(name.casefold())
        result.append({"id": slot_id, "name": name, "enabled": enabled})
    if not any(slot["enabled"] for slot in result):
        raise ApplicationError("Keep at least one meal slot enabled")
    if {slot["id"] for slot in previous} - ids:
        raise ApplicationError("Disable existing slots instead of deleting their IDs")
    return result


def text(value, label: str, maximum: int = 3000, *, optional: bool = False) -> str:
    if optional and value is None:
        return ""
    if not isinstance(value, str) or len(value.strip()) > maximum or (not optional and not value.strip()):
        raise ApplicationError(f"{label} must be {'nonempty ' if not optional else ''}text of at most {maximum} characters")
    return value.strip()


def identifier(value=None) -> str:
    try:
        return str(UUID(value)) if value else str(uuid4())
    except (ValueError, TypeError, AttributeError) as exc:
        raise ApplicationError("Plan item and component IDs must be UUIDs") from exc


def positive(value, label="Quantity", *, optional=False):
    if value is None and optional:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApplicationError(f"{label} must be a positive number") from None
    if isinstance(value, bool) or not number.is_finite() or number <= 0 or number.as_tuple().exponent < -3:
        raise ApplicationError(f"{label} must be positive with at most 3 decimal places")
    return float(number)


def iso_date(value, *, optional=False):
    if value is None and optional:
        return None
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ApplicationError("Date must be in YYYY-MM-DD format") from None


def component(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ApplicationError("Every meal component must be an object")
    source = value.get("source", "ready")
    action = value.get("action", "serve")
    if source not in ("ready", "cook", "task", "external"):
        raise ApplicationError("Component source must be ready, cook, task, or external")
    if action not in ("cook", "heat", "serve"):
        raise ApplicationError("Component action must be cook, heat, or serve")
    if source == "cook" and not value.get("recipeId"):
        raise ApplicationError("A cook component needs a recipeId")
    if source == "task" and not value.get("taskId"):
        raise ApplicationError("A task component needs a taskId")
    if source != "task" and value.get("taskId"):
        raise ApplicationError("Use source task when linking a cooking task")
    for key in ("recipeId", "pantryItemId", "taskId"):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise ApplicationError(f"{key} must be an ID string")
    return {
        "id": identifier(value.get("id")), "name": text(value.get("name"), "Component name", 180),
        "quantity": positive(value.get("quantity"), optional=True),
        "unit": text(value.get("unit"), "Unit", 40, optional=True),
        "source": source, "action": action,
        "recipeId": value.get("recipeId") or None,
        "pantryItemId": value.get("pantryItemId") or None,
        "taskId": value.get("taskId") or None,
        "notes": text(value.get("notes"), "Component notes", optional=True),
    }
