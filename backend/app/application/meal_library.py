"""Reusable combinations, independent of dates, pantry lots, and cooking batches."""
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4

from .errors import ApplicationError
from .planning_model import component, identifier, positive, text


class MealLibrary:
    def __init__(self, repository):
        self.repository = repository

    async def search(self, query="", limit=50, offset=0):
        query = text(query, "Meal search", 200, optional=True)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ApplicationError("Meal limit must be between 1 and 100")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10000:
            raise ApplicationError("Meal offset must be between 0 and 10000")
        return await self.repository.search_meals(query, limit, offset)

    async def get(self, meal_id):
        if not meal_id:
            raise ApplicationError("Saved meal ID is required")
        meal = await self.repository.get_meal(identifier(meal_id))
        if not meal:
            raise ApplicationError("Saved meal was not found in this household")
        return meal

    async def save(self, value):
        if not isinstance(value, dict):
            raise ApplicationError("Meal must be an object")
        existing = await self.get(value["id"]) if value.get("id") else None
        if existing and existing.get("archivedAt"):
            raise ApplicationError("Archived meals cannot be edited")
        values = value.get("components")
        if not isinstance(values, list) or not 1 <= len(values) <= 30:
            raise ApplicationError("A saved meal needs between 1 and 30 components")
        cleaned, ids = [], set()
        for raw in values:
            item = component(raw)
            if item["source"] == "task" or item["taskId"] or item["pantryItemId"]:
                raise ApplicationError("Saved meals cannot reference dated tasks or pantry lots")
            if item["recipeId"]:
                recipe = await self.repository.get_recipe(item["recipeId"])
                if not recipe or recipe.get("archived_at"):
                    raise ApplicationError("Recipe was not found or is archived in this household")
                expected_source = "ready" if recipe.get("kind") == "ready_food" else "cook"
                if item["source"] != expected_source:
                    raise ApplicationError(f"Use a {expected_source} component for this library entry")
            if item["id"] in ids:
                raise ApplicationError("Meal component IDs must be unique")
            ids.add(item["id"])
            cleaned.append(item)
        return await self.repository.save_meal({"id": existing["id"] if existing else str(uuid4()),
            "name": text(value.get("name"), "Meal name", 180),
            "servings": positive(value.get("servings"), "Default servings"),
            "notes": text(value.get("notes"), "Meal notes", optional=True), "components": cleaned})

    async def save_combination(self, recipe_ids, servings, notes=None, name=None):
        if not isinstance(recipe_ids, list) or not 2 <= len(recipe_ids) <= 10:
            raise ApplicationError("Choose between 2 and 10 recipes or ready foods")
        if any(not isinstance(recipe_id, str) or not recipe_id for recipe_id in recipe_ids):
            raise ApplicationError("Choose existing recipes or ready foods")
        ids = [identifier(recipe_id) for recipe_id in recipe_ids]
        if len(set(ids)) != len(ids):
            raise ApplicationError("Choose each recipe or ready food only once")
        target = positive(servings, "Default servings")
        foods = []
        for recipe_id in ids:
            recipe = await self.repository.get_recipe(recipe_id)
            if not recipe or recipe.get("archived_at"):
                raise ApplicationError("Recipe or ready food was not found in this household")
            foods.append(recipe)
        title = name or " + ".join(recipe["title"] for recipe in foods)
        if len(title) > 180 and not name:
            title = f"{foods[0]['title'][:155]} + {len(foods) - 1} more"
        return await self.save({"name": title, "servings": target, "notes": notes,
            "components": [{"name": recipe["title"], "quantity": target, "unit": "servings",
                "source": "ready" if recipe.get("kind") == "ready_food" else "cook",
                "action": "serve" if recipe.get("kind") == "ready_food" else "cook",
                "recipeId": recipe["id"]} for recipe in foods]})

    async def archive(self, meal_id):
        meal = await self.get(meal_id)
        return await self.repository.archive_meal(meal["id"])


def copy_components(components, multiplier=Decimal(1)):
    return [{**row, "id": str(uuid4()), "quantity": float((Decimal(str(row["quantity"])) * multiplier)
            .quantize(Decimal(".001"), rounding=ROUND_CEILING)) if row.get("quantity") is not None else None}
            for row in components]


def components_from_plan(entry, tasks):
    """Resolve recipe batches to recipes; detach ephemeral inventory/task references."""
    lookup = {task["id"]: task for task in tasks}
    result = []
    for row in copy_components(entry["components"]):
        row.pop("recipeSnapshot", None)
        if row.get("source") == "task":
            recipe_id = lookup.get(row.get("taskId"), {}).get("recipeId")
            ready = lookup.get(row.get("taskId"), {}).get("recipeSnapshot", {}).get("kind") == "ready_food"
            row.update(source="cook" if recipe_id and not ready else "ready", recipeId=recipe_id,
                       action="cook" if recipe_id and not ready else "heat" if row.get("action") == "heat" else "serve")
        row.update(pantryItemId=None, taskId=None)
        result.append(row)
    return result
