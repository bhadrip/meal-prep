from fastapi.testclient import TestClient
import pytest

from app.config import MCP_AUTH_SCOPES
from app.main import app


HEADERS = {"Accept": "application/json, text/event-stream"}


def test_oauth_requests_only_identity_and_refresh_scopes():
    assert MCP_AUTH_SCOPES == ("openid", "email", "offline_access")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as value:
        yield value


def rpc(client: TestClient, method: str, params: dict, request_id: int = 1) -> dict:
    response = client.post(
        "/mcp",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    assert response.status_code == 200
    return response.json()["result"]


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
        "save_meal_plan",
        "save_shopping_list",
        "render_meal_plan",
        "render_shopping_list",
        "get_weekly_schedule",
        "save_weekly_schedule",
        "get_latest_retro",
        "save_weekly_retro",
        "get_household_memory",
        "save_household_memory",
        "review_household_memory",
    }.issubset(names)
    render_tool = next(tool for tool in tools if tool["name"] == "render_meal_plan")
    assert render_tool["_meta"]["ui"]["resourceUri"].startswith("ui://meal-prep/")
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


def test_demo_retro_is_saved_as_evidence(client: TestClient):
    retro = {"weekStart": "2026-09-21", "outcomes": [{"meal": "Pasta", "outcome": "cooked"}], "workedWell": ["Quick meals"], "stressors": ["Too many dishes"], "note": "Keep Wednesday light."}
    saved = rpc(client, "tools/call", {"name": "save_weekly_retro", "arguments": {"retro": retro}}, request_id=3)["structuredContent"]
    assert saved["stressors"] == ["Too many dishes"]
    loaded = rpc(client, "tools/call", {"name": "get_latest_retro", "arguments": {}}, request_id=4)["structuredContent"]
    assert loaded["retro"]["note"] == "Keep Wednesday light."


def test_demo_memory_requires_explicit_review(client: TestClient):
    saved = rpc(client, "tools/call", {"name": "save_household_memory", "arguments": {"memory": {"content": "Keep Wednesday meals quick", "category": "schedule", "status": "suggested", "sourceType": "retro"}}}, request_id=5)["structuredContent"]
    assert saved["status"] == "suggested"
    confirmed = rpc(client, "tools/call", {"name": "review_household_memory", "arguments": {"memory_id": saved["id"], "action": "confirm"}}, request_id=6)["structuredContent"]
    assert confirmed["status"] == "confirmed"
    memories = rpc(client, "tools/call", {"name": "get_household_memory", "arguments": {}}, request_id=7)["structuredContent"]
    assert any(item["id"] == saved["id"] for item in memories["items"])


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
