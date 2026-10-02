"""Faceted browsing over the same household recipes used by the graph."""
from .errors import ApplicationError
from .recipe_graph import CATEGORY_FIELDS


def normalize_categories(values, field: str) -> list[str]:
    if not isinstance(values, list) or len(values) > 12:
        raise ApplicationError(f"{field} must be a list of at most 12 categories")
    labels = []
    for value in values:
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 48:
            raise ApplicationError(f"{field} categories must be text of 1–48 characters")
        label = " ".join(value.split()).lower()
        if label not in labels:
            labels.append(label)
    return labels


def browse(data: dict, query: str = "", filters: dict | None = None,
           max_minutes: int | None = None, limit: int = 25, offset: int = 0) -> dict:
    if not isinstance(query, str) or len(query) > 80:
        raise ApplicationError("Search must be text of at most 80 characters")
    if filters is not None and (not isinstance(filters, dict) or any(key not in CATEGORY_FIELDS for key in filters)):
        raise ApplicationError("Choose a valid recipe filter")
    normalized = {key: normalize_categories(values, key) for key, values in (filters or {}).items()}
    selected = {key: values for key, values in normalized.items() if values}
    if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or offset < 0:
        raise ApplicationError("Use a limit of 1–50 and a nonnegative offset")
    if max_minutes is not None and (type(max_minutes) is not int or not 1 <= max_minutes <= 1440):
        raise ApplicationError("Cooking time must be 1–1440 minutes")
    needle = query.strip().lower()
    recipes = sorted(data["recipes"], key=lambda r: (r["title"].lower(), r["id"]))

    def labels(recipe, kind):
        return set(recipe.get(CATEGORY_FIELDS[kind]) or [])

    def matches(recipe, excluding=None):
        minutes = recipe.get("total_minutes", recipe.get("totalMinutes"))
        if max_minutes is not None and (not isinstance(minutes, (int, float)) or minutes > max_minutes):
            return False
        text = [str(recipe.get("title") or ""), str(recipe.get("description") or "")]
        text.extend(str(i.get("name", "")) if isinstance(i, dict) else str(i) for i in (recipe.get("ingredients") or []))
        text.extend(label for field in CATEGORY_FIELDS.values() for label in (recipe.get(field) or []))
        if needle and not any(needle in value.lower() for value in text):
            return False
        return all(key == excluding or labels(recipe, key).intersection(values) for key, values in selected.items())

    facets = {}
    for kind in CATEGORY_FIELDS:
        options = set(selected.get(kind, [])) | {label for r in recipes for label in labels(r, kind)}
        facets[kind] = [{"label": label, "count": sum(label in labels(r, kind) and matches(r, kind) for r in recipes)}
                        for label in sorted(options)]
    matching = [r for r in recipes if matches(r)]
    active_ids = {r["id"] for r in recipes}
    variations = {}
    for edge in data["relationships"]:
        if edge["type"] == "variant_of" and edge["sourceRecipeId"] in active_ids and edge["targetRecipeId"] in active_ids:
            variations[edge["targetRecipeId"]] = variations.get(edge["targetRecipeId"], 0) + 1
    items = [{**r, "variationCount": variations.get(r["id"], 0)} for r in matching[offset:offset + limit]]
    return {"items": items, "count": len(matching), "totalCount": len(recipes), "facets": facets,
            "matchingRecipeIds": [r["id"] for r in matching],
            "query": query.strip(), "filters": selected, "maxMinutes": max_minutes,
            "limit": limit, "offset": offset, "hasMore": offset + len(items) < len(matching)}
