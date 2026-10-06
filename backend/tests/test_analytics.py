"""Authenticated analytics across the shared service and MCP entry points."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials

from app import analytics
from app.application.errors import ApplicationError, RepositoryError
from app.application.services import MemoryService
from app.config import Settings
from app.main import app
from app.transports import http
from app.transports import mcp_logging


class FakePostHogClient:
    events = []
    fail = False

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, json):
        if self.fail:
            raise httpx.ConnectError("unavailable")
        self.events.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))


@pytest.fixture
def capture(monkeypatch):
    FakePostHogClient.events = []
    FakePostHogClient.fail = False
    monkeypatch.setattr(analytics.httpx, "AsyncClient", FakePostHogClient)
    monkeypatch.setattr(analytics, "get_settings", lambda: Settings(
        auth_required=True, posthog_project_token="test-project-token", _env_file=None,
    ))
    return FakePostHogClient


@pytest.mark.asyncio
async def test_memory_outcomes_use_supabase_identity_without_content_and_skip_failures(capture):
    user_id = str(uuid4())
    repo = SimpleNamespace(
        save_household_memory=AsyncMock(return_value={"status": "suggested", "content": "Avoid peanuts"}),
        review_household_memory=AsyncMock(return_value={"status": "confirmed", "content": "Avoid peanuts"}),
    )
    actor = analytics.Analytics(user_id, analytics.RequestTelemetry("web", "request-1", str(uuid4())))
    service = MemoryService(repo, actor)
    await service.save({"content": "Avoid peanuts"})
    await service.review("memory-id", "confirm")
    assert [body["event"] for _, body in capture.events] == ["household_memory_saved", "household_memory_reviewed"]
    assert all(body["distinct_id"] == user_id for _, body in capture.events)
    assert all(body["properties"]["entry_point"] == "web" for _, body in capture.events)
    assert capture.events[1][1]["properties"]["action"] == "confirm"
    assert "Avoid peanuts" not in str(capture.events)
    assert all(url == "https://us.i.posthog.com/i/v0/e/" for url, _ in capture.events)

    with pytest.raises(ApplicationError):
        await service.review("memory-id", "invalid")
    repo.review_household_memory.side_effect = RepositoryError("private failure")
    with pytest.raises(RepositoryError):
        await service.review("memory-id", "forget")
    assert len(capture.events) == 2


@pytest.mark.asyncio
async def test_analytics_outage_does_not_change_saved_action(capture):
    capture.fail = True
    repo = SimpleNamespace(save_household_memory=AsyncMock(return_value={"status": "suggested"}))
    service = MemoryService(repo, analytics.Analytics(str(uuid4()), None))
    assert (await service.save({"content": "Keep Tuesday quick"}))["status"] == "suggested"
    repo.save_household_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_mcp_tool_capture_uses_verified_subject_and_records_failure_without_arguments(capture, monkeypatch):
    user_id = str(uuid4())
    monkeypatch.setattr(analytics, "get_access_token", lambda: SimpleNamespace(subject=user_id))
    server = analytics.TrackedFastMCP("analytics-test")

    @server.tool()
    async def echo(value: str) -> str:
        if value == "bad":
            raise ValueError("private ingredient")
        return value

    assert await server.call_tool("echo", {"value": "private recipe"})
    with pytest.raises(Exception):
        await server.call_tool("echo", {"value": "bad"})
    assert await server.list_tools()
    assert [body["event"] for _, body in capture.events] == ["$mcp_tool_call", "$mcp_tool_call", "$mcp_tools_list"]
    assert [body["properties"]["$mcp_is_error"] for _, body in capture.events[:2]] == [False, True]
    assert all(body["distinct_id"] == user_id for _, body in capture.events)
    assert all(body["properties"]["$mcp_tool_name"] == "echo" for _, body in capture.events[:2])
    assert all(body["properties"]["$mcp_source"] == "posthog_mcp_analytics" for _, body in capture.events)
    assert capture.events[2][1]["properties"]["$mcp_listed_tool_names"] == ["echo"]
    assert "private recipe" not in str(capture.events)
    assert "private ingredient" not in str(capture.events)


@pytest.mark.asyncio
async def test_web_dependency_passes_verified_supabase_subject(monkeypatch):
    user_id = str(uuid4())
    monkeypatch.setattr(http, "get_settings", lambda: Settings(
        supabase_url="https://example.supabase.co", supabase_anon_key="anon", auth_required=True, _env_file=None,
    ))

    async def verified(self, token):
        assert token == "signed-token"
        return SimpleNamespace(token=token, subject=user_id)

    monkeypatch.setattr(http.SupabaseTokenVerifier, "verify_token", verified)
    passed = []
    monkeypatch.setattr(http, "services_for_request", lambda token, user_id=None: passed.append((token, user_id)))
    await http.web_services(HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token"))
    assert passed == [("signed-token", user_id)]


def test_verified_api_writes_report_success_and_failure_without_body(capture, monkeypatch):
    user_id = str(uuid4())
    settings = Settings(supabase_url="https://example.supabase.co", supabase_anon_key="anon",
                        auth_required=True, posthog_project_token="test-project-token", _env_file=None)
    monkeypatch.setattr(http, "get_settings", lambda: settings)
    verify = AsyncMock(return_value=SimpleNamespace(token="signed-token", subject=user_id))
    monkeypatch.setattr(http, "SupabaseTokenVerifier", lambda _: SimpleNamespace(verify_token=verify))
    update = AsyncMock(return_value={"householdSize": 2})
    monkeypatch.setattr(http, "services_for_request", lambda token, user_id: SimpleNamespace(
        household=SimpleNamespace(update_preferences=update)))
    client = TestClient(app)
    headers = {"Authorization": "Bearer signed-token", "X-Meal-Prep-Client": "ios",
               "X-PostHog-Session-Id": str(uuid4())}

    result = client.patch("/api/household", json={"dietaryRestrictions": ["private food"]}, headers=headers)
    assert result.status_code == 200
    update.side_effect = ApplicationError("private failure")
    failure = client.patch("/api/household", json={"dietaryRestrictions": ["private food"]}, headers=headers)
    assert failure.status_code == 422
    verify.return_value = None
    denied = client.patch("/api/household", json={"dietaryRestrictions": ["private food"]}, headers=headers)
    assert denied.status_code == 401

    events = [body for _, body in capture.events if body["event"] == "api_mutation"]
    assert [event["properties"]["status"] for event in events] == [200, 422]
    assert [event["properties"]["success"] for event in events] == [True, False]
    assert all(event["distinct_id"] == user_id for event in events)
    assert all(event["properties"]["entry_point"] == "ios" for event in events)
    assert all(event["properties"]["route"] == "/api/household" for event in events)
    assert all("private food" not in str(event) and "private failure" not in str(event) for event in events)


def test_stateless_mcp_call_still_has_a_request_scoped_session():
    first = analytics._session_id({}, "mcp")
    second = analytics._session_id({}, "mcp")
    assert first.startswith("ses_") and len(first) == 36
    assert first != second


@pytest.mark.asyncio
async def test_mcp_event_and_vercel_log_share_request_id_without_session_token(capture, caplog, monkeypatch):
    user_id = str(uuid4())
    monkeypatch.setattr(analytics, "get_access_token", lambda: SimpleNamespace(subject=user_id))
    sent = []

    async def endpoint(scope, receive, send):
        await receive()
        await analytics.analytics_for_request().capture("mcp_probe")
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"result":{}}', "more_body": False})

    async def receive():
        return {"type": "http.request", "body": b'{"method":"tools/list"}', "more_body": False}

    async def send(message):
        sent.append(message)

    wrapped = analytics.AnalyticsRequestMiddleware(mcp_logging.MCPResponseLoggingMiddleware(endpoint))
    await wrapped({"type": "http", "method": "POST", "path": "/mcp",
                   "headers": [(b"mcp-session-id", b"private-session")]}, receive, send)
    log = next(json.loads(record.message) for record in caplog.records
               if record.name == mcp_logging.logger.name)
    event = capture.events[0][1]
    assert event["distinct_id"] == user_id
    assert event["properties"]["request_id"] == log["request_id"]
    assert event["properties"]["$session_id"].startswith("ses_")
    assert "private-session" not in json.dumps(event)
    assert (b"x-mcp-request-id", log["request_id"].encode()) in sent[0]["headers"]
