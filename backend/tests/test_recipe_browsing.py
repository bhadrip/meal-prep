import pytest
from fastapi.testclient import TestClient

from app.application.errors import ApplicationError
from app.application.services import PlanningService, RecipePantryService
from app.infrastructure.repositories import DemoRepository, demo_repository
from app.main import app


@pytest.mark.asyncio
async def test_browse_combines_facets_counts_other_options_and_searches_full_library():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    for index in range(28):
        await service.save_recipe({"title": f"A filler {index}"})
    tofu = await service.save_recipe({"title": "Tofu bhurji", "cuisines": [" North   Indian "],
        "eating_goals": ["Protein Rich"], "meal_types": ["dinner", "lunch"], "diets": ["vegan"],
        "totalMinutes": 20, "ingredients": [{"name": "tofu"}]})
    paneer = await service.save_recipe({"title": "Paneer bhurji", "cuisines": ["north indian"],
        "eating_goals": ["protein rich"], "meal_types": ["dinner"], "diets": ["vegetarian"], "totalMinutes": 35})
    rasam = await service.save_recipe({"title": "Rasam", "cuisines": ["south indian"], "meal_types": ["dinner"], "totalMinutes": 20})
    result = await service.browse_recipe_library(filters={"goal": ["Protein Rich"], "meal": ["dinner"]})
    assert {r["id"] for r in result["items"]} == {tofu["id"], paneer["id"]}
    assert result["count"] == 2 and result["totalCount"] == 31
    assert result["filters"]["goal"] == ["protein rich"]
    assert {o["label"]: o["count"] for o in result["facets"]["diet"]} == {"vegan": 1, "vegetarian": 1}
    # Facets count candidates with all other groups applied; alternatives in their own group remain visible.
    both = await service.browse_recipe_library(filters={"diet": ["vegan", "vegetarian"], "goal": ["protein rich"]})
    assert both["count"] == 2
    timed = await service.browse_recipe_library(max_minutes=20)
    assert {r["id"] for r in timed["items"]} == {tofu["id"], rasam["id"]}  # unknown times excluded
    assert (await service.browse_recipe_library(query="tofu"))["items"][0]["id"] == tofu["id"]
    edited = await service.save_recipe({**tofu, "totalMinutes": 40})
    assert edited["total_minutes"] == 40
    assert tofu["id"] not in {r["id"] for r in (await service.browse_recipe_library(max_minutes=20))["items"]}
    first = await service.browse_recipe_library(limit=25)
    second = await service.browse_recipe_library(limit=25, offset=25)
    assert first["hasMore"] and not second["hasMore"]
    assert len({r["id"] for r in first["items"] + second["items"]}) == 31
    assert len(first["matchingRecipeIds"]) == 31
    assert len((await service.get_recipe_graph())["matchingRecipeIds"]) == 31
    assert (await service.browse_recipe_library(filters={"cuisine": ["imagined"]}))["count"] == 0
    await service.archive_recipe(paneer["id"])
    assert (await service.browse_recipe_library(filters={"goal": ["protein rich"]}))["count"] == 1


@pytest.mark.asyncio
async def test_partial_food_search_pages_through_hundreds_of_names_and_excludes_archived_food():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    recipes = [await service.save_recipe({"title": f"Quinoa {index:03}"}) for index in range(110)]
    ready = await service.save_recipe({"title": "Quinoa snack cup", "kind": "ready_food"})
    described = await service.save_recipe({"title": "Korean tofu rice bowls", "description": "Serve with quinoa"})
    ingredient = await service.save_recipe({"title": "No-cook couscous bowls", "ingredients": [{"name": "quinoa"}]})
    meal = await PlanningService(repository).meals.save({"name": "Quinoa family dinner", "servings": 2,
        "components": [{"name": "Quinoa", "source": "external"}]})
    other_meal = await PlanningService(repository).meals.save({"name": "Rice family dinner", "servings": 2,
        "components": [{"name": "Quinoa", "source": "external"}]})
    broad = await service.browse_recipe_library(query="quino", item_type="all", limit=25)
    assert broad["count"] == 115
    pages = [await service.browse_recipe_library(query="quino", item_type="all", search_scope="name", limit=25, offset=offset)
             for offset in range(0, 125, 25)]
    found = [item for page in pages for item in page["items"]]
    assert pages[0]["count"] == 112
    assert [page["hasMore"] for page in pages] == [True, True, True, True, False]
    assert len(found) == len({item["id"] for item in found}) == 112
    assert {described["id"], ingredient["id"], other_meal["id"]}.isdisjoint({item["id"] for item in found})
    assert {item["id"]: item["itemType"] for item in found if item["id"] in {ready["id"], meal["id"]}} == {
        ready["id"]: "ready_food", meal["id"]: "meals"}
    assert recipes[-1]["id"] in {item["id"] for item in found}
    assert (await service.browse_recipe_library(query="no-such-food", item_type="all"))["items"] == []
    assert (await service.browse_recipe_library(query="no-such-food", item_type="all", search_scope="name"))["items"] == []
    await service.archive_recipe(recipes[-1]["id"])
    assert (await service.browse_recipe_library(query="Quinoa 109", item_type="all"))["items"] == []


@pytest.mark.asyncio
async def test_categories_are_editable_in_graph_and_preserved_by_older_recipe_updates():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    base = await service.save_recipe({"title": "Rasam"})
    pepper = await service.save_recipe({"title": "Pepper rasam"})
    for kind, label in [("cuisine", "South Indian"), ("goal", "Comfort food"), ("meal", "Dinner"), ("diet", "Vegan")]:
        edge = await service.save_recipe_relationship({"sourceRecipeId": base["id"], "type": kind, "label": label})
        assert (await service.browse_recipe_library(filters={kind: [label]}))["items"][0]["id"] == base["id"]
        with pytest.raises(ApplicationError, match="already exists"):
            await service.save_recipe_relationship({**edge, "id": None})
    await service.save_recipe_relationship({"sourceRecipeId": pepper["id"], "targetRecipeId": base["id"], "type": "variant_of"})
    assert (await service.browse_recipe_library(query="Rasam"))["items"][1]["variationCount"] == 1
    await service.save_recipe({"id": base["id"], "title": "Edited rasam"})
    assert (await service.get_recipe(base["id"]))["meal_types"] == ["dinner"]
    await service.delete_recipe_relationship(edge["id"])
    assert (await service.browse_recipe_library(filters={"diet": ["vegan"]}))["count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [
    {"filters": {"healthy": ["yes"]}}, {"filters": {"meal": "dinner"}},
    {"filters": {"diet": ["x" * 49]}}, {"filters": {"diet": None}},
    {"filters": []}, {"max_minutes": -1}, {"limit": 51}, {"offset": -1}, {"query": "x" * 81},
    {"search_scope": "unknown"},
])
async def test_invalid_filters_fail_without_changing_saved_data(arguments):
    repository = DemoRepository()
    service = RecipePantryService(repository)
    before = await service.get_recipe_graph()
    with pytest.raises(ApplicationError):
        await service.browse_recipe_library(**arguments)
    if not any(key in arguments for key in ("limit", "offset", "search_scope")):
        with pytest.raises(ApplicationError):
            await service.get_recipe_graph(**arguments)
    assert await service.get_recipe_graph() == before


@pytest.mark.asyncio
async def test_result_graph_follows_filters_and_keeps_only_direct_active_neighbors():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    base = await service.save_recipe({"title": "Rasam", "meal_types": ["dinner"], "totalMinutes": 15})
    variant = await service.save_recipe({"title": "Pepper rasam", "meal_types": ["lunch"], "totalMinutes": 30})
    partner = await service.save_recipe({"title": "Rice", "meal_types": ["lunch"]})
    unrelated = await service.save_recipe({"title": "Soup", "meal_types": ["dinner"], "totalMinutes": 15})
    await service.save_recipe_relationship({"sourceRecipeId": variant["id"], "targetRecipeId": base["id"], "type": "variant_of"})
    await service.save_recipe_relationship({"sourceRecipeId": partner["id"], "targetRecipeId": base["id"], "type": "pairs_with"})
    graph = await service.get_recipe_graph(query="rasam", filters={"meal": ["Dinner"]}, max_minutes=20)
    recipes = {n["recipeId"]: n for n in graph["nodes"] if n["kind"] == "recipe"}
    assert graph["matchingRecipeIds"] == [base["id"]] and graph["count"] == 1
    assert recipes[base["id"]]["isMatch"] is True
    assert recipes[variant["id"]]["isMatch"] is False and recipes[partner["id"]]["isMatch"] is False
    assert unrelated["id"] not in recipes  # sharing a category does not flood the graph
    assert {e["type"] for e in graph["edges"]} >= {"variant_of", "pairs_with", "meal"}
    assert graph["scope"] == {"query": "rasam", "filters": {"meal": ["dinner"]}, "maxMinutes": 20}
    # Editing can still link any active recipe; graph navigation stays within these results.
    assert unrelated["id"] in {r["recipeId"] for r in graph["recipeChoices"]}
    await service.archive_recipe(variant["id"])
    archived = await service.get_recipe_graph(query="rasam", filters={"meal": ["dinner"]})
    assert not any(n.get("recipeId") == variant["id"] for n in archived["nodes"])
    assert not any(r["recipeId"] == variant["id"] for r in archived["recipeChoices"])
    empty = await service.get_recipe_graph(query="imagined")
    assert empty["nodes"] == [] and empty["edges"] == [] and empty["count"] == 0


@pytest.mark.asyncio
async def test_main_search_result_ids_open_the_same_recipe_and_graph_with_stale_card_failure():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    for index in range(26):
        await service.save_recipe({"title": f"A filler {index}"})
    saved = await service.save_recipe({"title": "Pepper rasam", "meal_types": ["dinner"]})
    assert saved["id"] not in {r["id"] for r in (await service.browse_recipe_library())["items"]}
    result = await service.browse_recipe_library(query="PEPPER", filters={"meal": ["dinner"]})
    recipe_id = result["items"][0]["id"]
    assert (await service.get_recipe(recipe_id))["title"] == saved["title"]
    graph = await service.get_recipe_graph(query="PEPPER", filters={"meal": ["dinner"]})
    assert graph["matchingRecipeIds"] == [recipe_id]
    assert any(n["id"] == f"recipe:{recipe_id}" and n["label"] == saved["title"] for n in graph["nodes"])
    await service.archive_recipe(recipe_id)
    with pytest.raises(ApplicationError, match="not found"):
        await service.get_recipe(recipe_id)
    assert (await service.browse_recipe_library(query="PEPPER"))["count"] == 0
    assert (await service.get_recipe_graph(query="PEPPER"))["nodes"] == []


def test_http_browse_and_invalid_classification_save():
    demo_repository.cache_clear()
    client = TestClient(app)
    recipe = client.put('/api/recipes', json={"title": "HTTP tofu", "eating_goals": ["Protein Rich"], "meal_types": ["dinner"], "totalMinutes": 20}).json()
    response = client.get('/api/recipe-library', params={"goal": "protein rich", "meal": "dinner", "max_minutes": 20})
    assert response.status_code == 200 and response.json()["items"][0]["id"] == recipe["id"]
    assert client.get('/api/recipe-library?goal=protein%20rich&meal=breakfast').json()["count"] == 0
    assert client.get('/api/recipe-library?max_minutes=-1').status_code == 422
    graph = client.get('/api/recipe-graph', params={"query": "HTTP tofu", "goal": "protein rich", "meal": "dinner", "max_minutes": 20})
    assert graph.status_code == 200 and graph.json()["matchingRecipeIds"] == [recipe["id"]]
    assert client.get('/api/recipe-graph?meal=breakfast&query=HTTP%20tofu').json()["nodes"] == []
    assert client.get('/api/recipe-graph?max_minutes=-1').status_code == 422
    invalid = client.put('/api/recipes', json={"id": recipe["id"], "title": "Bad edit", "meal_types": [""]})
    assert invalid.status_code == 422
    assert client.get(f'/api/recipes/{recipe["id"]}').json()["title"] == "HTTP tofu"
    demo_repository.cache_clear()
