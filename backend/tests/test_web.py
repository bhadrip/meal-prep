from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.application.errors import RepositoryError, StorageNotInstalledError
from app.application.services import RecipePantryService
from app.config import Settings
from app.infrastructure.repositories import demo_repository
from app.main import app
from app.transports import http


def test_website_uses_plugin_logo_and_self_hosted_type():
    client = TestClient(app)
    landing = client.get("/")
    assert landing.status_code == 200
    assert "Connect the MCP server" in landing.text
    assert 'href="/app"' in landing.text
    assert "https://meal-prep-swart.vercel.app/mcp" in landing.text
    assert 'id="copy-mcp"' in landing.text
    html = client.get("/app").text
    assert '/static/meal-prep-icon.svg' in html
    assert '/static/typography.css' in html
    assert 'id="sidebar-toggle"' in html
    assert '<symbol id="icon-pantry"' in html
    assert html.count('formnovalidate') == 2
    assert 'value="cancel" formnovalidate>Cancel</button>' in html
    assert client.get("/static/typography.css").status_code == 200
    assert 'background: #252a40' in client.get("/static/app.css").text
    script = client.get("/static/app.js").text
    assert "routeFromUrl()" in script
    assert "addEventListener('popstate'" in script
    assert "encodeURIComponent(location.pathname + location.search + location.hash)" in script
    assert "location.replace(next || '/app')" in client.get("/static/login.js").text

    plugin_logo = Path(__file__).resolve().parents[2] / "plugin/assets/meal-prep-icon.svg"
    assert client.get("/static/meal-prep-icon.svg").text == plugin_logo.read_text()


def test_retired_weekly_review_api_is_not_exposed():
    client = TestClient(app)
    assert client.get("/api/retros").status_code == 404
    assert client.put("/api/retros", json={"note": "Old format"}).status_code == 404


def test_local_website_edits_share_application_data_across_requests():
    demo_repository.cache_clear()
    client = TestClient(app)
    assert client.get("/app").status_code == 200
    assert client.get("/api/health").json()["website"] == "/"

    recipe = client.put("/api/recipes", json={"title": "Local lentil bowls", "servings": 2})
    assert recipe.status_code == 200
    recipe_id = recipe.json()["id"]
    recipes = client.get("/api/recipes?query=Local").json()["items"]
    assert any(item["id"] == recipe_id for item in recipes)

    pantry = client.put("/api/pantry", json={"name": "Lentils", "quantity": 1})
    assert pantry.status_code == 200
    snapshot = client.get("/api/app/snapshot").json()
    assert any(item["name"] == "Lentils" for item in snapshot["sections"]["pantry"]["value"])
    assert "retro" not in snapshot["sections"]

    invalid = client.put("/api/meal-plan", json={"weekStart": "2026-09-28", "entries": [{"meal": "Soup"}]})
    assert invalid.status_code == 422
    assert "meal slot" in invalid.json()["detail"]

    plan = client.put("/api/meal-plan", json={"weekStart": "2026-09-28", "entries": [{"date": "2026-09-28", "slot": "dinner", "meal": "Soup"}]})
    assert plan.status_code == 200
    assert client.get("/api/meal-plan?week_start=2026-09-28").json()["plan"]["entries"][0]["meal"] == "Soup"

    archived = client.delete(f"/api/recipes/{recipe_id}")
    assert archived.status_code == 200
    assert all(item["id"] != recipe_id for item in client.get("/api/recipes").json()["items"])
    demo_repository.cache_clear()


def test_website_adds_shopping_items_with_optional_store():
    demo_repository.cache_clear()
    client = TestClient(app)
    current = client.get("/api/shopping-list").json()["shoppingList"]

    tagged = client.post("/api/shopping-list/items", json={"listId": current["id"], "item": {"name": "Olive oil", "store": "Trader Joe's"}})
    assert tagged.status_code == 200
    assert len(tagged.json()["items"]) == len(current["items"]) + 1
    assert tagged.json()["items"][-1]["store"] == "Trader Joe's"

    untagged = client.post("/api/shopping-list/items", json={"listId": current["id"], "item": {"name": "Salt"}})
    assert untagged.status_code == 200
    assert untagged.json()["items"][-1]["store"] is None
    assert client.get("/api/shopping-list").json()["shoppingList"]["items"][-2:] == untagged.json()["items"][-2:]

    script = client.get("/static/app.js").text
    assert "Where do you generally buy this? (optional)" in script
    assert "Usually: ${esc(item.store)}" in script
    demo_repository.cache_clear()


def test_web_api_requires_and_checks_supabase_session(monkeypatch):
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_anon_key="public-test-key",
        auth_required=True,
    )
    monkeypatch.setattr(http, "get_settings", lambda: settings)
    verify = AsyncMock(return_value=None)
    monkeypatch.setattr(http, "SupabaseTokenVerifier", lambda _: SimpleNamespace(verify_token=verify))
    client = TestClient(app)
    assert client.get("/api/household").status_code == 401
    assert client.get("/api/household", headers={"Authorization": "Bearer bad"}).status_code == 401
    verify.assert_awaited_once_with("bad")

    verify.return_value = SimpleNamespace(token="valid")
    household = SimpleNamespace(get_context=AsyncMock(return_value={"householdId": "test"}))
    captured = []
    monkeypatch.setattr(http, "services_for_request", lambda token: captured.append(token) or SimpleNamespace(household=household))
    response = client.get("/api/household", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.json() == {"householdId": "test"}
    assert captured == ["valid"]


def test_repository_details_are_not_sent_to_browser(monkeypatch):
    monkeypatch.setattr(http, "get_settings", lambda: Settings(supabase_url="", supabase_anon_key=""))
    food = SimpleNamespace(
        get_recipe=AsyncMock(side_effect=RepositoryError("Apply the checked-in Supabase migrations"))
    )
    monkeypatch.setattr(http, "services_for_request", lambda: SimpleNamespace(food=food))

    response = TestClient(app).get("/api/recipes/recipe-1")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "This part of Meal Prep is temporarily unavailable. Please try again later."
    }


def test_recipe_api_returns_recipe_when_feedback_store_is_missing(monkeypatch):
    monkeypatch.setattr(http, "get_settings", lambda: Settings(supabase_url="", supabase_anon_key=""))
    repository = SimpleNamespace(
        get_recipe=AsyncMock(return_value={"id": "recipe-1", "title": "Lentil soup"}),
        get_feedback=AsyncMock(side_effect=StorageNotInstalledError("feedback")),
    )
    monkeypatch.setattr(
        http,
        "services_for_request",
        lambda: SimpleNamespace(food=RecipePantryService(repository)),
    )

    response = TestClient(app).get("/api/recipes/recipe-1")

    assert response.status_code == 200
    assert response.json()["title"] == "Lentil soup"
    assert response.json()["feedbackUnavailable"] is True


def test_local_website_can_share_copy_and_revoke_a_recipe():
    demo_repository.cache_clear()
    client = TestClient(app)
    recipe = client.put("/api/recipes", json={
        "title": "Shareable lentil soup", "description": "Weeknight soup",
        "servings": 2, "ingredients": [{"name": "Lentils"}],
        "instructions": ["Simmer lentils"],
    }).json()
    share_response = client.post(f"/api/recipes/{recipe['id']}/shares")
    assert share_response.status_code == 200
    share = share_response.json()
    assert share["url"].endswith(f"/s/{share['token']}")
    assert client.get(f"/s/{share['token']}").status_code == 200
    assert any(item["id"] == share["id"] for item in client.get("/api/recipe-shares").json()["items"])

    copy_response = client.post(f"/api/shares/{share['token']}/save")
    assert copy_response.status_code == 200
    copied = client.get(f"/api/recipes/{copy_response.json()['recipeId']}").json()
    assert copied["title"] == recipe["title"]
    assert copied["id"] != recipe["id"]

    assert client.delete(f"/api/recipe-shares/{share['id']}").json()["revoked"]
    assert client.get(f"/s/{share['token']}").status_code == 404
    demo_repository.cache_clear()
