from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

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
    assert "/login?next=%2Fapp" in client.get("/static/app.js").text
    assert "location.replace(next || '/app')" in client.get("/static/login.js").text

    plugin_logo = Path(__file__).resolve().parents[2] / "plugin/assets/meal-prep-icon.svg"
    assert client.get("/static/meal-prep-icon.svg").text == plugin_logo.read_text()


def test_retired_weekly_review_api_is_not_exposed():
    client = TestClient(app)
    assert client.get("/api/retros").status_code == 404
    assert client.put("/api/retros", json={"note": "Old format"}).status_code == 404


def test_weekly_reviews_are_visible_and_saved_as_feedback():
    demo_repository.cache_clear()
    client = TestClient(app)
    html = client.get("/app").text
    mobile_nav = html.split('<nav class="mobile-nav"', 1)[1].split("</nav>", 1)[0]
    assert 'data-view="reviews"' in mobile_nav
    script = client.get("/static/app.js").text
    assert "Review this week" in script
    assert "Lesson learned or change for next time" in script

    saved = client.post("/api/feedback", json={
        "weekStart": "2026-09-28",
        "feedbackType": "worked_well",
        "note": "Sunday prep made lunches easy.",
        "nextTime": "Prep extra vegetables.",
        "tags": ["weekly-check-in"],
    })
    assert saved.status_code == 200
    assert saved.json()["feedback_type"] == "worked_well"
    assert saved.json()["next_time"] == "Prep extra vegetables."
    reviews = client.get("/api/feedback?week_start=2026-09-28").json()["items"]
    assert any(item["id"] == saved.json()["id"] for item in reviews)
    demo_repository.cache_clear()


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
    updated_recipe = client.put("/api/recipes", json={
        "id": recipe_id, "title": "Local lentil bowls", "description": "Updated in the browser",
        "servings": 3,
    })
    assert updated_recipe.status_code == 200
    assert client.get(f"/api/recipes/{recipe_id}").json()["description"] == "Updated in the browser"

    pantry = client.put("/api/pantry", json={"name": "Lentils", "quantity": 1})
    assert pantry.status_code == 200
    assert client.put("/api/pantry", json={
        "id": pantry.json()["id"], "name": "Lentils", "quantity": 2,
    }).status_code == 200
    snapshot = client.get("/api/app/snapshot").json()
    assert any(item["name"] == "Lentils" and item["quantity"] == 2 for item in snapshot["sections"]["pantry"]["value"])
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


def test_web_household_dashboard_and_weekly_schedule_lifecycle():
    demo_repository.cache_clear()
    client = TestClient(app)
    assert client.get("/api/household").status_code == 200

    updated = client.patch("/api/household", json={
        "householdSize": 3,
        "dietaryRestrictions": [],
        "storePriority": [{"store": "Safeway", "priority": 1}],
        "planningPreferences": {"weeknightMaxMinutes": 25, "leftoversForLunch": False},
        "completeOnboarding": True,
    })
    assert updated.status_code == 200
    assert client.get("/api/household").json()["householdSize"] == 3

    layout = client.patch("/api/dashboard-layout", json={
        "cardOrder": ["shopping-list"], "hiddenCards": ["pantry"],
    })
    assert layout.status_code == 200
    assert client.get("/api/dashboard-layout").json()["cardOrder"][0] == "shopping-list"
    assert client.get("/api/dashboard-layout").json()["hiddenCards"] == ["pantry"]
    assert client.patch("/api/dashboard-layout", json={"resetToDefault": True}).json()["hiddenCards"] == []

    week = "2030-02-04"
    days = [{"day": day, "mode": "quick"} for day in (
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    )]
    saved = client.put("/api/schedule", json={"weekStart": week, "days": days})
    assert saved.status_code == 200
    assert client.get(f"/api/schedule?week_start={week}").json()["schedule"]["days"] == days
    assert client.get(f"/api/planning-context?week_start={week}").json()["schedule"]["days"] == days
    demo_repository.cache_clear()


def test_web_shopping_list_create_progress_edit_and_remove():
    demo_repository.cache_clear()
    client = TestClient(app)
    current = client.get("/api/shopping-list").json()["shoppingList"]
    item_id = str(uuid4())
    items = [*current["items"], {
        "id": item_id, "name": "UI contract apples", "quantity": 4,
        "unit": "each", "store": "Safeway", "purchased": False,
    }]
    saved = client.put("/api/shopping-list", json={**current, "items": items})
    assert saved.status_code == 200
    assert any(item["id"] == item_id for item in client.get("/api/shopping-list").json()["shoppingList"]["items"])

    purchased = client.patch(f"/api/shopping-list/items/{item_id}", json={"purchased": True})
    assert purchased.status_code == 200
    assert purchased.json()["purchased"] is True
    updated_items = [{**item, "quantity": 5} if item["id"] == item_id else item for item in items]
    assert client.put("/api/shopping-list", json={**current, "items": updated_items}).status_code == 200
    assert next(item for item in client.get("/api/shopping-list").json()["shoppingList"]["items"] if item["id"] == item_id)["quantity"] == 5
    assert client.put("/api/shopping-list", json={**current, "items": current["items"]}).status_code == 200
    assert all(item["id"] != item_id for item in client.get("/api/shopping-list").json()["shoppingList"]["items"])
    demo_repository.cache_clear()


def test_web_feedback_and_memory_lifecycle():
    demo_repository.cache_clear()
    client = TestClient(app)
    week = "2030-02-04"
    saved = client.post("/api/feedback", json={
        "weekStart": week, "feedbackType": "worked_well", "note": "UI contract quick dinner",
        "tags": ["easy cleanup"],
    })
    assert saved.status_code == 200
    feedback_id = saved.json()["id"]
    assert any(item["id"] == feedback_id for item in client.get(f"/api/feedback?week_start={week}").json()["items"])
    assert any(item["id"] == feedback_id for item in client.get(f"/api/what-worked?week_start={week}").json()["items"])

    recipe_id = "11111111-1111-1111-1111-111111111111"
    recipe_feedback = client.post("/api/feedback", json={
        "recipeId": recipe_id, "weekStart": week, "feedbackType": "worked_well",
        "note": "The paneer was popular",
    })
    assert recipe_feedback.status_code == 200
    assert any(item["id"] == recipe_feedback.json()["id"] for item in client.get(f"/api/recipes/{recipe_id}").json()["feedback"])
    lessons = client.get(f"/api/recipes/{recipe_id}/lessons")
    assert lessons.status_code == 200
    assert any(item["id"] == recipe_feedback.json()["id"] for item in lessons.json()["workedWell"])

    memory = client.post("/api/memories", json={"content": "Keep Thursdays simple", "scope": "this_week"})
    assert memory.status_code == 200
    memory_id = memory.json()["id"]
    assert any(item["id"] == memory_id for item in client.get("/api/memories?status=suggested&scope=this_week").json()["items"])
    assert client.patch(f"/api/memories/{memory_id}", json={"action": "confirm"}).json()["status"] == "confirmed"
    assert client.patch(f"/api/memories/{memory_id}", json={"action": "update", "content": "Keep Friday simple"}).json()["content"] == "Keep Friday simple"
    assert client.patch(f"/api/memories/{memory_id}", json={"action": "forget"}).json()["active"] is False
    assert all(item["id"] != memory_id for item in client.get("/api/memories").json()["items"])
    assert any(item["id"] == memory_id for item in client.get("/api/memories?include_inactive=true").json()["items"])
    demo_repository.cache_clear()
