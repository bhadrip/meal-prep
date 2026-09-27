from fastapi.testclient import TestClient

from app.main import app
from app.state import STATE
import pytest


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    STATE.reset()
    yield
    STATE.reset()


def complete_onboarding():
    return client.post(
        "/api/interactions",
        json={
            "action": "complete_onboarding",
            "parameters": {
                "householdSize": 3,
                "dietaryRestrictions": ["vegetarian"],
                "plannedDinners": 4,
                "weekShape": "busy",
                "pantryStatus": "mostly_current",
                "stressors": ["Too much prep"],
                "successfulStrategies": ["Planned leftovers"],
            },
        },
    )


def test_first_visit_collects_practical_onboarding_context():
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["view_id"] == "onboarding"
    assert response.json()["components"][1]["type"] == "onboarding_form"

    completed = complete_onboarding()
    assert completed.status_code == 200
    assert completed.json()["view_id"] == "home"
    assert STATE.household_size == 3
    assert STATE.stressors == ["Too much prep"]
    assert STATE.successful_strategies == ["Planned leftovers"]


def test_dashboard_is_a_valid_view_spec():
    complete_onboarding()
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["components"][0]["type"] == "hero_meal"
    assert all(component["type"] for component in body["components"])


def test_make_easier_uses_bounded_choices_without_model():
    complete_onboarding()
    response = client.post("/api/interactions", json={"action": "make_easier"})
    assert response.status_code == 200
    body = response.json()
    choices = next(item for item in body["components"] if item["type"] == "choice_group")
    assert len(choices["data"]["choices"]) == 4


def test_swap_requires_confirmation_and_is_idempotent():
    complete_onboarding()
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
