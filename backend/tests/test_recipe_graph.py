from urllib.parse import quote
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.application.errors import ApplicationError
from app.application.services import RecipePantryService
from app.infrastructure.repositories import DemoRepository, demo_repository
from app.main import app


@pytest.mark.asyncio
async def test_graph_covers_full_library_and_category_edit_updates_recipe_tags():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    recipes = [await service.save_recipe({"title": f"Recipe {index}"}) for index in range(30)]
    first = recipes[0]["id"]
    edge = await service.save_recipe_relationship({"sourceRecipeId": first, "type": "tag", "label": "  Protein   Rich "})
    assert edge["label"] == "protein rich"
    assert (await service.search_recipes(tag="protein rich"))[0]["id"] == first
    assert len([n for n in (await service.get_recipe_graph())["nodes"] if n["kind"] == "recipe"]) == 30
    # The searchable graph picker needs the full household library, including recipes past the card page.
    last = recipes[-1]
    assert last["id"] not in {r["id"] for r in await service.search_recipes(limit=25)}
    assert any(n["label"] == last["title"] and n["recipeId"] == last["id"]
               for n in (await service.get_recipe_graph())["nodes"] if n["kind"] == "recipe")
    assert (await service.get_recipe(last["id"]))["title"] == last["title"]
    with pytest.raises(ApplicationError, match="not found"):
        await service.get_recipe(str(uuid4()))
    cuisine = await service.save_recipe_relationship({"id": edge["id"], "sourceRecipeId": first, "type": "cuisine", "label": "South Indian"})
    assert (await service.list_recipe_tags()) == []
    assert (await service.get_recipe(first))["cuisines"] == ["south indian"]
    await service.save_recipe({"id": first, "title": "Edited recipe", "tags": []})
    assert (await service.get_recipe(first))["cuisines"] == ["south indian"]
    await service.delete_recipe_relationship(cuisine["id"])
    assert (await service.get_recipe(first))["cuisines"] == []
    with pytest.raises(ApplicationError, match="not found"):
        await service.delete_recipe_relationship(cuisine["id"])


@pytest.mark.asyncio
async def test_variations_reject_cycles_and_pairings_are_symmetric_and_edits_atomic():
    repository = DemoRepository()
    repository._recipes = []
    service = RecipePantryService(repository)
    a, b, c = [(await service.save_recipe({"title": title}))["id"] for title in ("Rasam", "Tomato rasam", "Pepper rasam")]
    e = await service.save_recipe_relationship({"sourceRecipeId": b, "targetRecipeId": a, "type": "variant_of"})
    second = await service.save_recipe_relationship({"sourceRecipeId": c, "targetRecipeId": b, "type": "variant_of"})
    original = await service.get_recipe_graph()
    with pytest.raises(ApplicationError, match="loop"):
        await service.save_recipe_relationship({"id": second["id"], "sourceRecipeId": a, "targetRecipeId": b, "type": "variant_of"})
    assert await service.get_recipe_graph() == original
    pair = await service.save_recipe_relationship({"sourceRecipeId": b, "targetRecipeId": a, "type": "pairs_with"})
    assert pair["sourceRecipeId"] < pair["targetRecipeId"]
    with pytest.raises(ApplicationError, match="already exists"):
        await service.save_recipe_relationship({"sourceRecipeId": a, "targetRecipeId": b, "type": "pairs_with"})
    await service.archive_recipe(a)
    graph = await service.get_recipe_graph()
    assert all(edge["id"] not in (e["id"], pair["id"]) for edge in graph["edges"])
    with pytest.raises(ApplicationError, match="not found"):
        await service.save_recipe_relationship({"sourceRecipeId": b, "targetRecipeId": a, "type": "pairs_with"})


@pytest.mark.asyncio
async def test_category_limits_and_invalid_payloads_leave_state_unchanged():
    service = RecipePantryService(DemoRepository())
    recipe_id = (await service.save_recipe({"title": "Sambar", "tags": [f"tag{i}" for i in range(12)]}))["id"]
    initial = await service.get_recipe_graph()
    for payload, message in [
        ({"type": "invalid"}, "valid relationship"),
        ({"type": "tag", "sourceRecipeId": str(uuid4()), "label": "x"}, "not found"),
        ({"type": "tag", "label": []}, "must be text"),
        ({"type": "tag", "label": " "}, "must be text"),
        ({"type": "tag", "label": "x" * 49}, "must be text"),
        ({"type": "tag", "label": "thirteenth"}, "at most 12"),
        ({"type": "pairs_with", "targetRecipeId": recipe_id}, "different recipes"),
        ({"type": "tag", "label": "x", "id": "unknown"}, "not found"),
    ]:
        with pytest.raises(ApplicationError, match=message):
            await service.save_recipe_relationship({"sourceRecipeId": recipe_id, **payload})
        assert await service.get_recipe_graph() == initial
    # Mutating one demo repository must never change another caller's starting state.
    assert not any(n["label"] == "Sambar" for n in (await RecipePantryService(DemoRepository()).get_recipe_graph())["nodes"])


@pytest.fixture
def client():
    demo_repository.cache_clear()
    yield TestClient(app)
    demo_repository.cache_clear()


def test_http_graph_edit_roundtrip_and_duplicate_failure(client):
    recipe_id = client.put('/api/recipes', json={"title": "Tofu bhurji"}).json()["id"]
    payload = {"sourceRecipeId": recipe_id, "type": "tag", "label": "protein rich"}
    saved = client.put('/api/recipe-relationships', json=payload)
    assert saved.status_code == 200
    edge = saved.json()
    assert any(e["id"] == edge["id"] for e in client.get('/api/recipe-graph').json()["edges"])
    assert client.put('/api/recipe-relationships', json=payload).status_code == 422
    assert client.get(f'/api/recipes/{recipe_id}').json()["tags"] == ["protein rich"]
    assert client.delete('/api/recipe-relationships/' + quote(edge["id"], safe='')).json()["deleted"] is True
    assert client.get(f'/api/recipes/{recipe_id}').json()["tags"] == []
    assert client.delete('/api/recipe-relationships/' + quote(edge["id"], safe='')).status_code == 422
