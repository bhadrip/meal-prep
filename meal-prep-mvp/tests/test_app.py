from fastapi.testclient import TestClient

from app.main import app
from app.state import STATE


client = TestClient(app)


def test_dashboard_is_a_valid_view_spec():
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["components"][0]["type"] == "hero_meal"
    assert all(component["type"] for component in body["components"])


def test_make_easier_uses_bounded_choices_without_model():
    response = client.post("/api/interactions", json={"action": "make_easier"})
    assert response.status_code == 200
    body = response.json()
    choices = next(item for item in body["components"] if item["type"] == "choice_group")
    assert len(choices["data"]["choices"]) == 4


def test_swap_requires_confirmation_and_is_idempotent():
    original = STATE.active_meal_id
    target = "sesame-noodles" if original != "sesame-noodles" else "lemon-chicken"
    preview = client.post(
        "/api/interactions", json={"action": "select_swap", "target_id": target}
    )
    assert preview.status_code == 200
    assert preview.json()["components"][0]["type"] == "confirmation"

    payload = {
        "action": "confirm_swap",
        "target_id": target,
        "idempotency_key": "test-idempotency-key",
    }
    first = client.post("/api/interactions", json=payload)
    version = STATE.version
    second = client.post("/api/interactions", json=payload)
    assert first.status_code == second.status_code == 200
    assert STATE.version == version

