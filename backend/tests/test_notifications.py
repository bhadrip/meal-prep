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
