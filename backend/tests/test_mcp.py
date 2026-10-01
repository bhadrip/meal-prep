from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.config import MCP_AUTH_SCOPES
from app.infrastructure.repositories import DemoRepository, demo_repository
from app.main import app


HEADERS = {"Accept": "application/json, text/event-stream"}
DEFAULT_DEMO_CONTEXT = deepcopy(DemoRepository._context)


def test_mcp_recipe_dropdown_selection_records_use_and_rejects_missing_recipe(client):
    def call(name, arguments, request_id):
        return rpc(client, "tools/call", {"name": name, "arguments": arguments}, request_id)

    recipe = call("save_recipe", {"recipe": {"title": "Dropdown test soup"}}, 910)["structuredContent"]
    item = call("update_pantry_item", {"item": {"name": "Dropdown test lentils", "quantity": 1, "unit": "cup"}}, 911)["structuredContent"]
    saved = call("record_pantry_use", {"item_id": item["id"], "quantity": 0.25, "recipe_id": recipe["id"]}, 912)["structuredContent"]
    assert saved["recipeId"] == recipe["id"]
    assert saved["recipeTitle"] == "Dropdown test soup"
    assert saved["quantityRemaining"] == 0.75
    rejected = call("record_pantry_use", {"item_id": item["id"], "quantity": 0.25, "recipe_id": "missing-recipe"}, 913)
    assert rejected["isError"] is True
    assert "Recipe was not found" in str(rejected["content"])
    pantry = call("get_pantry", {}, 914)["structuredContent"]["items"]
    assert next(row for row in pantry if row["id"] == item["id"])["quantity"] == 0.75


def test_mcp_dropdown_assets_are_embedded_for_hosts_without_static_asset_access(client):
    for uri in ("ui://meal-prep/onboarding-v2.html", "ui://meal-prep/household-dashboard-v4.html"):
        html = rpc(client, "resources/read", {"uri": uri})["contents"][0]["text"]
        assert '/static/choices.js' not in html
        assert '/static/choices.css' not in html
        assert '<select' not in html
        assert 'window.MealPrepChoices =' in html


def test_oauth_requests_only_identity_and_refresh_scopes():
    assert MCP_AUTH_SCOPES == ("openid", "email", "offline_access")


@pytest.fixture(scope="module")
def client():
    DemoRepository._context = deepcopy(DEFAULT_DEMO_CONTEXT)
    demo_repository.cache_clear()
    with TestClient(app) as value:
        yield value
    demo_repository.cache_clear()


def rpc(client: TestClient, method: str, params: dict, request_id: int = 1) -> dict:
    response = client.post(
        "/mcp",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_http_surface_serves_website_and_mcp(client: TestClient):
    root = client.get("/app")
    assert root.status_code == 200
    assert "Meal Prep" in root.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/app/snapshot").status_code == 200
    login_script = client.get("/static/login.js")
    assert login_script.status_code == 200
    assert "shouldCreateUser: true" in login_script.text
    assert client.get("/invite").status_code == 200


def test_pantry_categories_roundtrip_through_mcp_and_snapshot(client: TestClient):
    def call(name, arguments, request_id):
        return rpc(client, "tools/call", {"name": name, "arguments": arguments}, request_id=request_id)

    chili = call("update_pantry_item", {"item": {"name": "Chili oil", "quantity": 1}}, 801)["structuredContent"]
    mystery = call("update_pantry_item", {"item": {"name": "Mystery tin", "quantity": 1}}, 802)["structuredContent"]
    assert chili["category"] == "condiments"
    assert mystery["category"] == "uncategorized"
    changed = call("update_pantry_item", {"item": {"id": mystery["id"], "name": "Mystery tin", "category": "snacks", "quantity": 1}}, 803)["structuredContent"]
    assert changed["category"] == "snacks"
    invalid = call("update_pantry_item", {"item": {"id": chili["id"], "name": "Chili oil", "category": "anything"}}, 804)
    assert invalid["isError"] is True
    assert "Invalid pantry category" in str(invalid["content"])
    items = call("get_pantry", {}, 805)["structuredContent"]["items"]
    assert {item["id"]: item["category"] for item in items}[chili["id"]] == "condiments"
    assert {item["id"]: item["category"] for item in items}[mystery["id"]] == "snacks"
    snapshot = call("render_household_snapshot", {}, 806)["structuredContent"]
    assert any(item["id"] == mystery["id"] and item["category"] == "snacks" for item in snapshot["sections"]["pantry"]["value"])


def test_mcp_initializes_and_exposes_domain_tools(client: TestClient):
    initialized = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    )
    assert initialized["serverInfo"]["name"] == "meal-prep"

    tools = rpc(client, "tools/list", {})["tools"]
    names = {tool["name"] for tool in tools}
    assert {
        "get_household_context",
        "get_dashboard_layout",
        "configure_dashboard",
        "save_meal_plan",
        "save_shopping_list",
        "add_shopping_item",
        "render_onboarding",
        "render_meal_plan",
        "render_shopping_list",
        "render_household_snapshot",
        "render_recipe_library",
        "render_feedback",
        "get_weekly_schedule",
        "save_weekly_schedule",
        "get_planning_context",
        "get_meal_plan_rules",
        "save_meal_plan_rules",
        "get_meal_plan_rule_history",
        "get_feedback",
        "save_feedback",
        "get_what_worked",
        "get_recipe_feedback_summary",
        "get_household_memory",
        "save_household_memory",
        "review_household_memory",
        "save_pantry_photo",
        "get_pantry_evidence",
        "apply_pantry_evidence",
        "render_pantry_evidence",
        "record_pantry_use",
    }.issubset(names)
    assert {"get_latest_retro", "get_weekly_retro", "save_weekly_retro"}.isdisjoint(names)
    add_tool = next(tool for tool in tools if tool["name"] == "add_shopping_item")
    assert "list_id" in add_tool["inputSchema"]["properties"]
    assert add_tool["annotations"]["idempotentHint"] is False
    use_tool = next(tool for tool in tools if tool["name"] == "record_pantry_use")
    assert use_tool["annotations"]["idempotentHint"] is False
    assert {"item_id", "quantity"}.issubset(use_tool["inputSchema"]["required"])

    contents = rpc(client, "resources/read", {"uri": "ui://meal-prep/household-dashboard-v4.html"})["contents"]
    html = contents[0]["text"]
    assert 'id="pantry-use-form"' in html
    assert "pantry-meter" in html
    render_uris = {
        tool["name"]: tool["_meta"]["ui"]["resourceUri"]
        for tool in tools
        if tool["name"].startswith("render_")
    }
    assert render_uris == {
        "render_household_snapshot": "ui://meal-prep/household-dashboard-v4.html",
        "render_recipe_library": "ui://meal-prep/recipe-library-v1.html",
        "render_feedback": "ui://meal-prep/feedback-v2.html",
        "render_onboarding": "ui://meal-prep/onboarding-v2.html",
        "render_meal_plan": "ui://meal-prep/meal-plan-v2.html",
        "render_shopping_list": "ui://meal-prep/shopping-list-v2.html",
        "render_pantry_evidence": "ui://meal-prep/pantry-evidence-v1.html",
    }
    photo_tool = next(tool for tool in tools if tool["name"] == "save_pantry_photo")
    assert photo_tool["_meta"]["openai/fileParams"] == ["file"]
    file_schema = photo_tool["inputSchema"]["$defs"]["ChatGPTPhotoFile"]
    assert set(file_schema["properties"]) == {"download_url", "file_id", "mime_type", "file_name"}
    assert set(file_schema["required"]) == {"download_url", "file_id"}
    assert file_schema["additionalProperties"] is False
    preferences_tool = next(tool for tool in tools if tool["name"] == "update_household_preferences")
    assert "complete_onboarding" in preferences_tool["inputSchema"]["properties"]


def test_demo_weekly_schedule_can_be_saved_and_read(client: TestClient):
    days = [
        {"day": day, "mode": "quick" if index < 5 else "flexible"}
        for index, day in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
    ]
    saved = rpc(client, "tools/call", {"name": "save_weekly_schedule", "arguments": {"schedule": {"weekStart": "2026-09-28", "days": days, "isNormalWeek": False}}})["structuredContent"]
    assert saved["days"] == days
    loaded = rpc(client, "tools/call", {"name": "get_weekly_schedule", "arguments": {"week_start": "2026-09-28"}}, request_id=2)["structuredContent"]
    assert loaded["schedule"]["is_normal_week"] is False


def test_shopping_item_tool_keeps_optional_store_in_rendered_list(client: TestClient):
    current = rpc(client, "tools/call", {"name": "get_shopping_list", "arguments": {}}, request_id=30)["structuredContent"]["shoppingList"]
    tagged = rpc(
        client,
        "tools/call",
        {"name": "add_shopping_item", "arguments": {"item": {"name": "Olive oil", "store": "Trader Joe's"}, "list_id": current["id"]}},
        request_id=31,
    )["structuredContent"]
    assert len(tagged["items"]) == len(current["items"]) + 1
    assert tagged["items"][-1]["store"] == "Trader Joe's"

    untagged = rpc(
        client,
        "tools/call",
        {"name": "add_shopping_item", "arguments": {"item": {"name": "Salt"}, "list_id": current["id"]}},
        request_id=32,
    )["structuredContent"]
    assert untagged["items"][-1]["store"] is None
    rendered = rpc(client, "tools/call", {"name": "render_shopping_list", "arguments": {"list_id": current["id"]}}, request_id=33)["structuredContent"]
    assert rendered["shoppingList"]["items"][-2:] == untagged["items"][-2:]

    contents = rpc(client, "resources/read", {"uri": "ui://meal-prep/shopping-list-v2.html"}, request_id=34)["contents"]
    html = contents[0]["text"]
    assert 'id="shopping-add-form"' in html
    assert 'Where do you generally buy this?' in html
    assert 'class="store-tag"' in html


def test_demo_weekly_check_in_is_saved_as_feedback(client: TestClient):
    saved = rpc(
        client,
        "tools/call",
        {
            "name": "save_feedback",
            "arguments": {
                "feedback": {
                    "weekStart": "2026-09-21",
                    "feedbackType": "worked_well",
                    "note": "Quick meals worked well.",
                    "tags": ["easy cleanup"],
                }
            },
        },
        request_id=3,
    )["structuredContent"]
    assert saved["feedback_type"] == "worked_well"

    loaded = rpc(
        client,
        "tools/call",
        {"name": "get_feedback", "arguments": {"week_start": "2026-09-21"}},
        request_id=4,
    )["structuredContent"]
    assert any(item["id"] == saved["id"] for item in loaded["items"])


def test_feedback_links_a_recipe_to_the_week_and_is_recalled_next_time(client: TestClient):
    days = [
        {"day": day, "mode": "quick"}
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    ]
    rpc(
        client,
        "tools/call",
        {
            "name": "save_weekly_schedule",
            "arguments": {"schedule": {"weekStart": "2026-09-28", "days": days}},
        },
        request_id=18,
    )
    recipe_id = "11111111-1111-1111-1111-111111111111"
    saved = rpc(
        client,
        "tools/call",
        {
            "name": "save_feedback",
            "arguments": {
                "feedback": {
                    "recipeId": recipe_id,
                    "weekStart": "2026-09-28",
                    "feedbackType": "change_next_time",
                    "note": "The sauce was too spicy for the kids.",
                    "nextTime": "Serve chili oil at the table instead.",
                    "tags": ["spice", "family:kids"],
                    "rating": 3,
                }
            },
        },
        request_id=19,
    )["structuredContent"]
    assert saved["occurrence"]["recipe_id"] == recipe_id
    assert saved["weekly_schedule_id"]

    filtered = rpc(
        client,
        "tools/call",
        {
            "name": "get_feedback",
            "arguments": {"recipe_id": recipe_id, "tags": ["family:kids"]},
        },
        request_id=20,
    )["structuredContent"]
    assert filtered["count"] >= 1
    assert filtered["items"][0]["next_time"] == "Serve chili oil at the table instead."

    recipe = rpc(
        client,
        "tools/call",
        {"name": "get_recipe", "arguments": {"recipe_id": recipe_id}},
        request_id=21,
    )["structuredContent"]
    assert any(item["id"] == saved["id"] for item in recipe["feedback"])

    summary = rpc(
        client,
        "tools/call",
        {"name": "get_recipe_feedback_summary", "arguments": {"recipe_id": recipe_id}},
        request_id=22,
    )["structuredContent"]
    assert summary["evidenceCount"] >= 1
    assert any(item["id"] == saved["id"] for item in summary["nextTime"])


def test_demo_memory_requires_explicit_review(client: TestClient):
    saved = rpc(client, "tools/call", {"name": "save_household_memory", "arguments": {"memory": {"content": "Keep Wednesday meals quick", "category": "schedule", "status": "suggested", "sourceType": "feedback"}}}, request_id=5)["structuredContent"]
    assert saved["status"] == "suggested"
    confirmed = rpc(client, "tools/call", {"name": "review_household_memory", "arguments": {"memory_id": saved["id"], "action": "confirm"}}, request_id=6)["structuredContent"]
    assert confirmed["status"] == "confirmed"
    memories = rpc(client, "tools/call", {"name": "get_household_memory", "arguments": {}}, request_id=7)["structuredContent"]
    assert any(item["id"] == saved["id"] for item in memories["items"])


def test_memory_defaults_to_suggested_and_can_be_filtered(client: TestClient):
    saved = rpc(
        client,
        "tools/call",
        {"name": "save_household_memory", "arguments": {"memory": {"content": "Tuesday may need a quick dinner", "scope": "this_week"}}},
        request_id=12,
    )["structuredContent"]
    assert saved["status"] == "suggested"
    filtered = rpc(
        client,
        "tools/call",
        {"name": "get_household_memory", "arguments": {"status": "suggested", "scope": "this_week"}},
        request_id=13,
    )["structuredContent"]
    assert [item["id"] for item in filtered["items"]] == [saved["id"]]


def test_planning_context_returns_all_durable_inputs(client: TestClient):
    context = rpc(
        client,
        "tools/call",
        {"name": "get_planning_context", "arguments": {"week_start": "2026-09-28"}},
        request_id=14,
    )["structuredContent"]
    assert context["household"]["householdId"]
    assert context["schedule"]["week_start"] == "2026-09-28"
    assert "feedback" in context
    assert "retro" not in context
    assert any(item["status"] == "confirmed" for item in context["memories"])


def test_mcp_english_rules_history_and_plan_provenance(client: TestClient):
    def call(name, arguments):
        return rpc(client, "tools/call", {"name": name, "arguments": arguments})

    current = call("get_meal_plan_rules", {})["structuredContent"]["rules"]
    first = call("save_meal_plan_rules", {"text": "Saturday pasta; Monday uses its leftovers.",
        "expected_revision": current["revision"] if current else 0})["structuredContent"]
    saved = call("save_meal_plan", {"plan": {"weekStart": "2030-02-04", "ruleRevisionId": first["id"],
        "entries": [{"date": "2030-02-04", "slot": "dinner", "meal": "Pasta leftovers"}]}})["structuredContent"]
    assert saved["ruleRevision"]["text"] == first["text"]
    second = call("save_meal_plan_rules", {"text": "Saturday stir-fry.", "expected_revision": first["revision"]})["structuredContent"]
    stale = call("save_meal_plan_rules", {"text": "Stale changes", "expected_revision": first["revision"]})
    assert stale["isError"] is True and "changed" in str(stale["content"])
    history = call("get_meal_plan_rule_history", {})["structuredContent"]["items"]
    assert history[:2] == [second, first]
    context = call("get_planning_context", {"week_start": "2030-02-11"})["structuredContent"]
    assert context["mealPlanRules"] == second
    assert context["recentPlans"][0]["ruleRevision"] == first
    assert call("get_meal_plan_rules", {"revision_id": first["id"]})["structuredContent"]["rules"] == first


def test_demo_household_context_and_plan_render_are_structured(client: TestClient):
    context = rpc(
        client,
        "tools/call",
        {"name": "get_household_context", "arguments": {}},
    )["structuredContent"]
    assert context["storePriority"][0]["store"] == "Costco"
    assert "no shellfish" in context["dietaryRestrictions"]
    assert context["onboardingComplete"] is True

    rendered = rpc(
        client,
        "tools/call",
        {"name": "render_meal_plan", "arguments": {}},
    )["structuredContent"]
    assert rendered["kind"] == "meal_plan"
    assert rendered["plan"]["entries"]


def test_household_snapshot_collects_chatgpt_ui_data_without_flattening_it_to_text(client: TestClient):
    rendered = rpc(
        client,
        "tools/call",
        {"name": "render_household_snapshot", "arguments": {}},
        request_id=10,
    )["structuredContent"]

    assert rendered["kind"] == "household_snapshot"
    assert rendered["household"]["householdSize"] == 4
    assert set(rendered["sections"]) == {
        "pantry", "recipes", "schedule", "feedback", "memories", "mealPlan", "shoppingList", "mealPlanRules"
    }
    assert rendered["sections"]["pantry"]["status"] in {"ready", "empty", "unavailable"}


def test_recipe_library_is_served_as_a_visual_mcp_app(client: TestClient):
    rendered = rpc(
        client,
        "tools/call",
        {"name": "render_recipe_library", "arguments": {}},
        request_id=24,
    )["structuredContent"]

    assert rendered["kind"] == "recipe_library"
    assert rendered["count"] == len(rendered["recipes"])
    assert rendered["recipes"][0]["title"] == "Paneer rice bowls"

    contents = rpc(
        client,
        "resources/read",
        {"uri": "ui://meal-prep/recipe-library-v1.html"},
        request_id=25,
    )["contents"]
    html = contents[0]["text"]
    assert "recipe-grid" in html
    assert "Ingredients" in html
    assert "Instructions" in html


def test_mcp_recipe_tags_save_search_and_render(client: TestClient):
    saved = rpc(client, "tools/call", {"name": "save_recipe", "arguments": {
        "recipe": {"title": "Ginger rasam", "tags": [" Sickness-Friendly ", "rasam"]}
    }})["structuredContent"]
    assert saved["tags"] == ["sickness-friendly", "rasam"]
    results = rpc(client, "tools/call", {"name": "search_recipes", "arguments": {
        "tag": "sickness-friendly"
    }})["structuredContent"]["items"]
    assert saved["id"] in [item["id"] for item in results]
    rendered = rpc(client, "tools/call", {"name": "render_recipe_library", "arguments": {
        "tag": "sickness-friendly"
    }})["structuredContent"]
    assert [item["id"] for item in rendered["recipes"]] == [saved["id"]]
    assert {item["tag"] for item in rendered["tags"]} >= {"sickness-friendly", "rasam"}
    assert rpc(client, "tools/call", {"name": "search_recipes", "arguments": {
        "tag": "sickness"
    }})["structuredContent"]["count"] == 0
    assert saved["id"] in [item["id"] for item in rpc(client, "tools/call", {
        "name": "search_recipes", "arguments": {"query": "sick"}
    })["structuredContent"]["items"]]
    tags = rpc(client, "tools/call", {"name": "list_recipe_tags", "arguments": {}})["structuredContent"]["items"]
    assert {item["tag"] for item in tags} >= {"sickness-friendly", "rasam"}
    assert all(item["tag"] != "invented-tag" for item in tags)


def test_feedback_is_served_separately_from_confirmed_preferences(client: TestClient):
    rendered = rpc(
        client,
        "tools/call",
        {"name": "render_feedback", "arguments": {}},
        request_id=26,
    )["structuredContent"]

    assert rendered["kind"] == "feedback"
    assert set(rendered["sections"]) == {"feedback"}
    assert rendered["sections"]["feedback"]["status"] in {"ready", "empty", "unavailable"}


def test_dashboard_layout_can_be_configured_incrementally_from_chat(client: TestClient):
    initial = rpc(
        client,
        "tools/call",
        {"name": "get_dashboard_layout", "arguments": {}},
        request_id=24,
    )["structuredContent"]
    assert initial["cardOrder"][0] == "food-rules"
    assert initial["hiddenCards"] == []

    configured = rpc(
        client,
        "tools/call",
        {
            "name": "configure_dashboard",
            "arguments": {
                "card_order": ["shopping-list"],
                "hidden_cards": ["feedback", "memories"],
            },
        },
        request_id=25,
    )["structuredContent"]
    assert configured["cardOrder"][0] == "shopping-list"
    assert configured["hiddenCards"] == ["feedback", "memories"]
    assert configured["household"]["planningPreferences"]["weeknightMaxMinutes"] == 30

    reset = rpc(
        client,
        "tools/call",
        {
            "name": "configure_dashboard",
            "arguments": {"reset_to_default": True},
        },
        request_id=26,
    )["structuredContent"]
    assert reset["cardOrder"] == initial["availableCards"]
    assert reset["hiddenCards"] == []


def test_onboarding_is_served_as_an_mcp_app(client: TestClient):
    rendered = rpc(
        client,
        "tools/call",
        {"name": "render_onboarding", "arguments": {}},
        request_id=15,
    )["structuredContent"]
    assert rendered["kind"] == "onboarding"
    assert "planningPreferences" in rendered["household"]

    resources = rpc(client, "resources/list", {}, request_id=16)["resources"]
    onboarding = next(resource for resource in resources if resource["uri"] == "ui://meal-prep/onboarding-v2.html")
    assert onboarding["mimeType"] == "text/html;profile=mcp-app"

    contents = rpc(
        client,
        "resources/read",
        {"uri": onboarding["uri"]},
        request_id=17,
    )["contents"]
    html = contents[0]["text"]
    assert "Feeding a family takes planning" in html
    assert "update_household_preferences" in html


def test_mcp_app_completes_the_standard_ui_handshake(client: TestClient):
    contents = rpc(
        client,
        "resources/read",
        {"uri": "ui://meal-prep/household-dashboard-v4.html"},
        request_id=18,
    )["contents"]
    html = contents[0]["text"]

    assert "protocolVersion: '2026-01-26'" in html
    assert "appCapabilities: {}" in html
    assert "appInfo: { name: 'meal-prep-ui', version: '1.5.0' }" in html
    assert "notify('ui/notifications/initialized')" in html
    assert html.index("await rpc('ui/initialize'") < html.index("notify('ui/notifications/initialized')")
    assert "clientInfo:" not in html


def test_household_dashboard_exposes_chat_configured_individual_cards(client: TestClient):
    contents = rpc(
        client,
        "resources/read",
        {"uri": "ui://meal-prep/household-dashboard-v4.html"},
        request_id=23,
    )["contents"]
    html = contents[0]["text"]

    for card_id in (
        "food-rules", "planning-defaults", "stores", "schedule", "meal-plan",
        "shopping-list", "pantry", "recipes", "feedback", "memories",
    ):
        assert f"id: '{card_id}'" in html
    assert "Ask Meal Prep in chat to show, hide, reorder, or reset dashboard cards." in html
    assert 'data-action="customize-dashboard"' not in html
    assert 'data-dashboard-toggle=' not in html


def test_household_onboarding_can_be_completed_only_with_full_answers(client: TestClient):
    incomplete = rpc(
        client,
        "tools/call",
        {
            "name": "update_household_preferences",
            "arguments": {"household_size": 2, "complete_onboarding": True},
        },
        request_id=8,
    )
    assert incomplete["isError"] is True
    assert "dietary_restrictions" in incomplete["content"][0]["text"]

    completed = rpc(
        client,
        "tools/call",
        {
            "name": "update_household_preferences",
            "arguments": {
                "household_size": 2,
                "dietary_restrictions": [],
                "store_priority": [{"store": "Local market", "priority": 1}],
                "planning_preferences": {
                    "weeknightMaxMinutes": 25,
                    "leftoversForLunch": False,
                },
                "complete_onboarding": True,
            },
        },
        request_id=9,
    )["structuredContent"]
    assert completed["householdSize"] == 2
    assert completed["onboardingCompletedAt"] != "2026-01-01T00:00:00+00:00"
