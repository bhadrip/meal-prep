from fastapi.testclient import TestClient
import pytest

from app.main import app


HEADERS = {"Accept": "application/json, text/event-stream"}


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
    }.issubset(names)
    render_tool = next(tool for tool in tools if tool["name"] == "render_meal_plan")
    assert render_tool["_meta"]["ui"]["resourceUri"].startswith("ui://meal-prep/")


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


def test_demo_household_context_and_plan_render_are_structured(client: TestClient):
    context = rpc(
        client,
        "tools/call",
        {"name": "get_household_context", "arguments": {}},
    )["structuredContent"]
    assert context["storePriority"][0]["store"] == "Costco"
    assert "no shellfish" in context["dietaryRestrictions"]

    rendered = rpc(
        client,
        "tools/call",
        {"name": "render_meal_plan", "arguments": {}},
    )["structuredContent"]
    assert rendered["kind"] == "meal_plan"
    assert rendered["plan"]["entries"]
