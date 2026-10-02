"""Explainable shopping suggestions from explicit plan quantities; no NLP or invented conversions."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_CEILING


UNITS = {
    "g": ("g", 1), "grams": ("g", 1), "gram": ("g", 1), "kg": ("g", 1000),
    "ml": ("ml", 1), "l": ("ml", 1000),
    "serving": ("servings", 1), "servings": ("servings", 1),
    "piece": ("pieces", 1), "pieces": ("pieces", 1),
    "cup": ("cups", 1), "cups": ("cups", 1),
    "pack": ("packs", 1), "packs": ("packs", 1),
}


def quantity_key(name, unit):
    normalized = str(unit or "").strip().casefold()
    base, factor = UNITS.get(normalized, (normalized, 1))
    return (" ".join(name.split()).casefold(), base), Decimal(factor)


def shopping_demand(plan: dict, pantry: list[dict]) -> dict:
    demands = {}
    warnings = []
    stock_by_id = {row["id"]: row for row in pantry}
    stock = defaultdict(Decimal)
    uncertain = set()
    for row in pantry:
        key, factor = quantity_key(row["name"], row.get("unit"))
        if row.get("quantity") is None or row.get("quantity_confidence", row.get("quantityConfidence")) != "exact":
            uncertain.add(key)
        else:
            stock[key] += Decimal(str(row["quantity"])) * factor

    def add(name, quantity, unit, reason, pantry_id=None):
        if quantity is None or not unit:
            warnings.append(f"Check quantity and unit for {name} ({reason['title']}).")
            return
        key, factor = quantity_key(name, unit)
        if pantry_id:
            row = stock_by_id.get(pantry_id)
            if row:
                stock_key, stock_factor = quantity_key(row["name"], row.get("unit"))
                if stock_key[1] != key[1]:
                    warnings.append(f"Check units for {name}: plan uses {unit}; pantry uses {row.get('unit') or 'unknown'}. No conversion assumed.")
                    return
                key = stock_key
        demand = demands.setdefault(key, {"name": name, "quantity": Decimal(0), "unit": key[1], "reasons": []})
        demand["quantity"] += Decimal(str(quantity)) * factor
        if reason not in demand["reasons"]:
            demand["reasons"].append(reason)

    def ingredients(record, reason, servings=None):
        recipe = record.get("recipeSnapshot") or {}
        target = servings or record.get("servings")
        if not recipe.get("servings") or target is None:
            warnings.append(f"Check recipe yield and planned servings for {reason['title']}.")
            return
        try:
            yield_amount = Decimal(str(recipe["servings"]))
            if not yield_amount.is_finite() or yield_amount <= 0:
                raise InvalidOperation()
            multiplier = Decimal(str(target)) / yield_amount
        except (InvalidOperation, ValueError, TypeError):
            warnings.append(f"Check recipe yield for {reason['title']}.")
            return
        for ingredient in recipe.get("ingredients") or []:
            if not isinstance(ingredient, dict):
                warnings.append(f"Check ingredient amounts for {reason['title']}.")
                continue
            amount = ingredient.get("quantity")
            try:
                amount = Decimal(str(amount)) * multiplier if amount is not None else None
                if amount is not None and (not amount.is_finite() or amount < 0):
                    raise InvalidOperation()
            except (InvalidOperation, ValueError, TypeError):
                amount = None
            if amount == 0:
                continue
            add(ingredient.get("name") or "Unnamed ingredient", amount, ingredient.get("unit"), reason, ingredient.get("pantryItemId"))

    tasks = {task["id"]: task for task in plan.get("tasks", [])}
    batch_use = defaultdict(Decimal)
    for task in tasks.values():
        if not task.get("completedAt") and task.get("recipeId"):
            ingredients(task, {"itemId": task["id"], "kind": "task", "title": task["title"]})
    for meal in plan["entries"]:
        if meal.get("completedAt"):
            continue
        reason = {"itemId": meal["id"], "kind": "meal", "title": meal["meal"]}
        if not meal.get("components"):
            warnings.append(f"Add components to {meal['meal']} to calculate its shopping needs.")
        for item in meal.get("components", []):
            source = item.get("source", "ready")
            if source == "external":
                continue
            if source == "cook":
                if item.get("unit") not in ("serving", "servings"):
                    warnings.append(f"Use servings for recipe component {item['name']} to scale its ingredients.")
                else:
                    ingredients(item, reason, item.get("quantity"))
            elif source == "task":
                task = tasks[item["taskId"]]
                if task.get("completedAt"):
                    outputs = task.get("stockOutputs", [])
                    output = next((row for row in outputs if row["name"].casefold() == item["name"].casefold()), None)
                    if not output and len(outputs) == 1:
                        output = outputs[0]
                    if output:
                        add(output["name"], item.get("quantity"), item.get("unit"), reason, output["itemId"])
                    else:
                        warnings.append(f"Check prepared stock for {item['name']}; {task['title']} has no recorded matching output.")
                elif item.get("quantity") is None or item.get("unit") not in ("serving", "servings"):
                    warnings.append(f"Check portions allocated from {task['title']} to {meal['meal']}.")
                else:
                    batch_use[task["id"]] += Decimal(str(item["quantity"]))
            else:
                add(item["name"], item.get("quantity"), item.get("unit"), reason, item.get("pantryItemId"))
    for task_id, allocated in batch_use.items():
        task = tasks[task_id]
        if task.get("servings") is None or allocated > Decimal(str(task["servings"])):
            warnings.append(f"{task['title']}: {allocated} servings allocated; planned yield is {task.get('servings') or 'unknown'}.")

    items = []
    for key, demand in demands.items():
        if key in uncertain:
            warnings.append(f"Check pantry quantity for {demand['name']}; only exact stock was subtracted.")
        # A name match with a different unit is not evidence of sufficient stock.
        if any(other[0] == key[0] and other[1] != key[1] for other in [*stock, *uncertain]):
            warnings.append(f"Check package/unit conversion for {demand['name']}; unmatched units were not subtracted.")
        shortage = max(Decimal(0), demand["quantity"] - stock[key])
        if shortage:
            items.append({"name": demand["name"], "quantity": float(shortage.quantize(Decimal('.001'), rounding=ROUND_CEILING)),
                          "unit": demand["unit"], "purchased": False,
                          "source": {"generated": True, "weekStart": plan["weekStart"], "reasons": demand["reasons"]}})
    return {"weekStart": plan["weekStart"], "mealPlanId": plan["id"], "items": items,
            "warnings": list(dict.fromkeys(warnings))}
