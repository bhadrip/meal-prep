"""Typed recipe relationships shared by the website and MCP."""

from .errors import ApplicationError


RELATIONSHIP_TYPES = {"cuisine": "Cuisine", "goal": "Eating goal", "meal": "Meal", "diet": "Diet", "tag": "Tag", "variant_of": "Variation of", "pairs_with": "Serve with"}
CATEGORY_FIELDS = {"cuisine": "cuisines", "goal": "eating_goals", "meal": "meal_types", "diet": "diets", "tag": "tags"}


def category_id(kind: str, recipe_id: str, label: str) -> str:
    return f"{kind}:{recipe_id}:{label}"


def relationships_from_data(data: dict) -> list[dict]:
    recipes = {r["id"]: r for r in data["recipes"]}
    result = []
    for recipe in recipes.values():
        for kind, field in CATEGORY_FIELDS.items():
            for label in dict.fromkeys(recipe.get(field) or []):
                result.append({"id": category_id(kind, recipe["id"], label), "sourceRecipeId": recipe["id"],
                               "type": kind, "label": label, "targetRecipeId": None})
    result.extend(r for r in data["relationships"]
                  if r["sourceRecipeId"] in recipes and r["targetRecipeId"] in recipes)
    return result


def build_graph(data: dict) -> dict:
    nodes = [{"id": f"recipe:{r['id']}", "kind": "recipe", "label": r["title"], "recipeId": r["id"]}
             for r in data["recipes"]]
    categories = {}
    edges = []
    for relationship in relationships_from_data(data):
        kind = relationship["type"]
        target = (f"{kind}:{relationship['label']}" if kind in CATEGORY_FIELDS
                  else f"recipe:{relationship['targetRecipeId']}")
        if kind in CATEGORY_FIELDS:
            categories[target] = {"id": target, "kind": kind, "label": relationship["label"]}
        edges.append({**relationship, "source": f"recipe:{relationship['sourceRecipeId']}", "target": target})
    nodes.extend(sorted(categories.values(), key=lambda n: (n["kind"], n["label"])))
    return {"nodes": nodes, "edges": edges, "relationshipTypes": RELATIONSHIP_TYPES}


def build_result_graph(data: dict, matching_recipe_ids: list[str]) -> dict:
    """Keep search matches and their directly linked variations/serving partners."""
    matching = set(matching_recipe_ids)
    active = {recipe["id"] for recipe in data["recipes"]}
    included = matching.copy()
    for relationship in data["relationships"]:
        source, target = relationship["sourceRecipeId"], relationship["targetRecipeId"]
        if source in active and target in active and (source in matching or target in matching):
            included.update((source, target))
    graph = build_graph({"recipes": [r for r in data["recipes"] if r["id"] in included],
                         "relationships": data["relationships"]})
    for node in graph["nodes"]:
        if node["kind"] == "recipe":
            node["isMatch"] = node["recipeId"] in matching
    return {**graph, "matchingRecipeIds": matching_recipe_ids, "count": len(matching),
            "recipeChoices": [{"recipeId": r["id"], "label": r["title"]}
                              for r in sorted(data["recipes"], key=lambda r: (r["title"].casefold(), r["id"]))]}


def validate_relationship(payload: dict, graph: dict) -> dict:
    kind = payload.get("type")
    if not isinstance(kind, str) or kind not in RELATIONSHIP_TYPES:
        raise ApplicationError("Choose a valid relationship type")
    recipes = {n["recipeId"] for n in graph["nodes"] if n["kind"] == "recipe"}
    source = payload.get("sourceRecipeId")
    if not isinstance(source, str) or source not in recipes:
        raise ApplicationError("Source recipe was not found in this household")
    old_id = payload.get("id")
    if old_id is not None and (not isinstance(old_id, str) or not any(e["id"] == old_id for e in graph["edges"])):
        raise ApplicationError("Relationship was not found")
    label, target = None, None
    if kind in CATEGORY_FIELDS:
        value = payload.get("label")
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 48:
            raise ApplicationError("Category must be text of 1–48 characters")
        label = " ".join(value.split()).lower()
    else:
        target = payload.get("targetRecipeId")
        if not isinstance(target, str) or target not in recipes:
            raise ApplicationError("Target recipe was not found in this household")
        if source == target:
            raise ApplicationError("Choose two different recipes")
        if kind == "pairs_with":
            source, target = sorted((source, target))
    others = [e for e in graph["edges"] if e["id"] != old_id]
    if any(e["type"] == kind and e["sourceRecipeId"] == source
           and e.get("targetRecipeId") == target and e.get("label") == label for e in others):
        raise ApplicationError("This relationship already exists")
    if kind in CATEGORY_FIELDS and sum(e["type"] == kind and e["sourceRecipeId"] == source for e in others) >= 12:
        raise ApplicationError("A recipe can have at most 12 categories of each kind")
    if kind == "variant_of":
        pending, seen = [target], set()
        while pending:
            node = pending.pop()
            if node == source:
                raise ApplicationError("This would create a loop in the variations")
            if node not in seen:
                seen.add(node)
                pending.extend(e["targetRecipeId"] for e in others if e["type"] == kind and e["sourceRecipeId"] == node)
    return {"id": old_id, "sourceRecipeId": source, "type": kind, "targetRecipeId": target, "label": label}
