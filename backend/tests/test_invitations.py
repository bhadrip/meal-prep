import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.invitations import deliver_invitation, invitation_repository
from app.main import app


@pytest.mark.asyncio
async def test_delivery_invites_new_user_with_server_secret(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"email": "new@example.test"})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client_type(transport=httpx.MockTransport(respond)))
    settings = Settings(
        app_base_url="https://meal.example.test",
        supabase_url="https://supabase.example.test",
        supabase_anon_key="public-key",
        supabase_secret_key="server-secret",
    )

    await deliver_invitation("new@example.test", settings)

    assert len(requests) == 1
    assert requests[0].url.path == "/auth/v1/invite"
    assert requests[0].url.params["redirect_to"] == "https://meal.example.test/invite"
    assert requests[0].headers["apikey"] == "server-secret"


@pytest.mark.asyncio
async def test_delivery_sends_existing_user_a_sign_in_link(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/invite"):
            return httpx.Response(422, json={"msg": "A user with this email is already registered"})
        return httpx.Response(200, json={})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client_type(transport=httpx.MockTransport(respond)))
    settings = Settings(
        app_base_url="https://meal.example.test",
        supabase_url="https://supabase.example.test",
        supabase_anon_key="public-key",
        supabase_secret_key="server-secret",
    )

    await deliver_invitation("existing@example.test", settings)

    assert [request.url.path for request in requests] == ["/auth/v1/invite", "/auth/v1/otp"]
    assert requests[1].headers["apikey"] == "public-key"
    assert b'"create_user":false' in requests[1].content


@pytest.mark.asyncio
async def test_delivery_does_not_report_success_on_auth_failure(monkeypatch):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_: client_type(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    )
    settings = Settings(
        app_base_url="https://meal.example.test",
        supabase_url="https://supabase.example.test",
        supabase_anon_key="public-key",
        supabase_secret_key="server-secret",
    )

    with pytest.raises(HTTPException) as error:
        await deliver_invitation("new@example.test", settings)
    assert error.value.status_code == 502


def test_invitation_api_sends_email_after_owner_checked_database_write(monkeypatch):
    calls = []

    class Repository:
        async def rpc(self, name, payload=None):
            calls.append((name, payload))
            return {"id": "00000000-0000-0000-0000-000000000042", "email": "wife@example.test"}

    async def repository_override():
        return Repository()

    async def fake_delivery(email, settings):
        calls.append(("deliver", email))

    monkeypatch.setattr("app.invitations.get_settings", lambda: Settings(supabase_secret_key="server-secret"))
    monkeypatch.setattr("app.invitations.deliver_invitation", fake_delivery)
    app.dependency_overrides[invitation_repository] = repository_override
    try:
        response = TestClient(app).post("/api/household/invitations", json={"email": "wife@example.test"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == [
        ("create_household_invitation", {"invitee_email": "wife@example.test"}),
        ("deliver", "wife@example.test"),
    ]


def test_invitation_api_revokes_unsent_invitation(monkeypatch):
    calls = []

    class Repository:
        async def rpc(self, name, payload=None):
            calls.append((name, payload))
            return {"id": "00000000-0000-0000-0000-000000000042", "email": "wife@example.test"}

    async def repository_override():
        return Repository()

    async def failed_delivery(email, settings):
        raise HTTPException(status_code=502, detail="Could not send the invitation email")

    monkeypatch.setattr("app.invitations.get_settings", lambda: Settings(supabase_secret_key="server-secret"))
    monkeypatch.setattr("app.invitations.deliver_invitation", failed_delivery)
    app.dependency_overrides[invitation_repository] = repository_override
    try:
        response = TestClient(app).post("/api/household/invitations", json={"email": "wife@example.test"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert calls[-1] == (
        "revoke_household_invitation",
        {"invitation_id": "00000000-0000-0000-0000-000000000042"},
    )
