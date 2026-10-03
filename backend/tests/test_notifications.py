import pytest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.infrastructure.repositories import SupabaseRepository
from app.main import app
from app.transports.http import web_services


NOTIFICATION_ID = "00000000-0000-0000-0000-000000000042"


def test_notification_api_lists_and_marks_read_with_caller_scoped_repository():
    repository = SupabaseRepository(
        Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None),
        "member-token",
    )
    repository.request = AsyncMock(side_effect=[
        [{"id": NOTIFICATION_ID, "kind": "shopping_lists", "title": "Shopping list updated",
          "target_path": "/app?view=shopping", "created_at": "2026-09-30T12:00:00Z", "read_at": None}],
        [{"id": NOTIFICATION_ID, "read_at": "2026-09-30T12:01:00Z"}],
    ])

    async def services_override():
        return SimpleNamespace(household=SimpleNamespace(repository=repository))

    app.dependency_overrides[web_services] = services_override
    try:
        client = TestClient(app)
        listing = client.get("/api/notifications")
        marked = client.patch(f"/api/notifications/{NOTIFICATION_ID}/read")
    finally:
        app.dependency_overrides.clear()

    assert listing.status_code == 200
    assert listing.json()["unreadCount"] == 1
    assert listing.json()["items"][0]["target_path"] == "/app?view=shopping"
    assert marked.status_code == 200
    assert marked.json()["readAt"] == "2026-09-30T12:01:00Z"
    assert repository.request.await_args_list[0].args == ("GET", "notifications")
    assert repository.request.await_args_list[1].kwargs["params"] == {"id": f"eq.{NOTIFICATION_ID}"}


def test_mark_read_rejects_notification_not_visible_to_caller():
    repository = SupabaseRepository(
        Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None),
        "other-member-token",
    )
    repository.request = AsyncMock(return_value=[])

    async def services_override():
        return SimpleNamespace(household=SimpleNamespace(repository=repository))

    app.dependency_overrides[web_services] = services_override
    try:
        response = TestClient(app).patch(f"/api/notifications/{NOTIFICATION_ID}/read")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Notification not found"


def test_archive_restore_and_unread_share_caller_scoped_operations():
    repository = SupabaseRepository(
        Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None),
        "member-token",
    )
    repository.request = AsyncMock(side_effect=[
        [{"id": NOTIFICATION_ID, "archived_at": "2026-10-02T12:00:00Z"}],
        [{"id": NOTIFICATION_ID, "archived_at": "2026-10-02T12:00:00Z", "read_at": None}],
        [{"id": NOTIFICATION_ID, "archived_at": None}],
        [{"id": NOTIFICATION_ID, "read_at": None}],
        [],
    ])

    async def services_override():
        return SimpleNamespace(household=SimpleNamespace(repository=repository))

    app.dependency_overrides[web_services] = services_override
    try:
        client = TestClient(app)
        archived = client.patch(f"/api/notifications/{NOTIFICATION_ID}/archive")
        listing = client.get("/api/notifications?archived=true")
        restored = client.patch(f"/api/notifications/{NOTIFICATION_ID}/archive?archived=false")
        unread = client.patch(f"/api/notifications/{NOTIFICATION_ID}/read?read=false")
        denied = client.patch(f"/api/notifications/{NOTIFICATION_ID}/archive")
    finally:
        app.dependency_overrides.clear()
    assert archived.json()["archivedAt"] == "2026-10-02T12:00:00Z"
    assert listing.json()["unreadCount"] == 0
    assert listing.json()["items"][0]["id"] == NOTIFICATION_ID
    assert repository.request.await_args_list[1].kwargs["params"]["archived_at"] == "not.is.null"
    assert restored.json()["archivedAt"] is None
    assert unread.json()["readAt"] is None
    assert repository.request.await_args_list[2].kwargs["json"] == {"archived_at": None}
    assert repository.request.await_args_list[3].kwargs["json"] == {"read_at": None}
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_direct_mcp_notification_state_and_failure(monkeypatch):
    import pytest
    from app.transports import mcp as transport
    repository = SupabaseRepository(
        Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None), "token")
    repository.request = AsyncMock(side_effect=[
        [{"id": NOTIFICATION_ID, "read_at": None}],
        [{"id": NOTIFICATION_ID, "archived_at": "now"}],
        [], [],
    ])
    monkeypatch.setattr(transport, "services_for_request", lambda: SimpleNamespace(household=SimpleNamespace(repository=repository)))
    assert (await transport.set_notification_read(NOTIFICATION_ID, False))["readAt"] is None
    assert (await transport.archive_notification(NOTIFICATION_ID))["archivedAt"] == "now"
    assert (await transport.list_notifications(True))["items"] == []
    with pytest.raises(ValueError, match="Notification not found"):
        await transport.archive_notification(NOTIFICATION_ID, False)
    with pytest.raises(ValueError):
        await transport.set_notification_read("invalid")
