from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.infrastructure.repositories import demo_repository
from app.main import app
from app.transports import http


def test_website_uses_plugin_logo_and_self_hosted_type():
    client = TestClient(app)
    html = client.get("/").text
    assert '/static/meal-prep-icon.svg' in html
    assert '/static/typography.css' in html
    assert 'id="sidebar-toggle"' in html
    assert '<symbol id="icon-pantry"' in html
    assert html.count('formnovalidate') == 2
    assert 'value="cancel" formnovalidate>Cancel</button>' in html
    assert client.get("/static/typography.css").status_code == 200
    assert 'background: #252a40' in client.get("/static/app.css").text

    plugin_logo = Path(__file__).resolve().parents[2] / "plugin/assets/meal-prep-icon.svg"
    assert client.get("/static/meal-prep-icon.svg").text == plugin_logo.read_text()


def test_local_website_edits_share_application_data_across_requests():
    demo_repository.cache_clear()
    client = TestClient(app)
    assert client.get("/").status_code == 200
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
