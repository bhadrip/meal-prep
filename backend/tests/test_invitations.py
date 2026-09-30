from fastapi.testclient import TestClient

from app.application.errors import RepositoryError
from app.invitations import _expected_error, invitation_repository
from app.main import app


def test_invitation_api_creates_pending_share_for_existing_account():
    calls = []

    class Repository:
        async def rpc(self, name, payload=None):
            calls.append((name, payload))
            return {"id": "00000000-0000-0000-0000-000000000042", "email": "wife@example.test"}

    async def repository_override():
        return Repository()

    app.dependency_overrides[invitation_repository] = repository_override
    try:
        response = TestClient(app).post("/api/household/invitations", json={"email": "wife@example.test"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["email"] == "wife@example.test"
    assert calls == [("create_household_invitation", {"invitee_email": "wife@example.test"})]


def test_invitation_requires_a_verified_account():
    error = _expected_error(
        RepositoryError("Ask this person to sign up and verify their email before inviting them")
    )
    assert error.status_code == 422


def test_household_selection_api_uses_checked_database_functions():
    calls = []

    class Repository:
        async def rpc(self, name, payload=None):
            calls.append((name, payload))
            return {"activeHouseholdId": "00000000-0000-0000-0000-000000000042", "households": []}

    async def repository_override():
        return Repository()

    app.dependency_overrides[invitation_repository] = repository_override
    try:
        client = TestClient(app)
        assert client.get("/api/households").status_code == 200
        assert client.post("/api/households", json={"name": "Second home"}).status_code == 200
        assert client.post("/api/households/00000000-0000-0000-0000-000000000042/activate").status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert calls == [
        ("list_my_households", None),
        ("create_my_household", {"requested_name": "Second home"}),
        ("set_active_household", {"requested_household_id": "00000000-0000-0000-0000-000000000042"}),
    ]
