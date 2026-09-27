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
    toast = completed.json()["components"][0]
    assert toast["type"] == "toast"
    assert toast["actions"] == []


def test_plan_flow_reuses_and_confirms_weekly_schedule():
    complete_onboarding()
    response = client.post("/api/interactions", json={"action": "show_plan"})
    assert response.status_code == 200
    assert response.json()["view_id"] == "schedule-check"
    schedule = next(item for item in response.json()["components"] if item["type"] == "schedule_check")
    assert schedule["data"]["days"][0] == {"day": "Monday", "mode": "quick"}

    changed = [dict(item) for item in schedule["data"]["days"]]
    changed[0]["mode"] = "out"
    saved = client.post(
        "/api/interactions",
        json={"action": "save_schedule", "parameters": {"days": changed, "isNormalWeek": False, "rememberRhythm": True}},
    )
    assert saved.status_code == 200
    assert saved.json()["view_id"] == "plan-review"
    assert STATE.previous_schedule[0]["mode"] == "out"
    assert STATE.schedule_confirmed is True


def test_retro_captures_evidence_before_next_schedule_check():
    complete_onboarding()
    STATE.retro_due = True
    response = client.post("/api/interactions", json={"action": "show_plan"})
    assert response.status_code == 200
    assert response.json()["view_id"] == "weekly-retro"
    meals = next(item for item in response.json()["components"] if item["type"] == "retro_form")["data"]["meals"]
    outcomes = [{"id": item["id"], "meal": item["meal"], "outcome": item["outcome"]} for item in meals]
    saved = client.post(
        "/api/interactions",
        json={"action": "save_retro", "parameters": {"outcomes": outcomes, "workedWell": ["Planned leftovers"], "stressors": ["Too much chopping"], "note": "Wednesday ran late."}},
    )
    assert saved.status_code == 200
    assert saved.json()["view_id"] == "schedule-check"
    assert STATE.latest_retro["stressors"] == ["Too much chopping"]
    assert STATE.retro_due is False
    suggestions = [item for item in STATE.memories if item["status"] == "suggested"]
    assert {item["source"] for item in suggestions} == {"Weekly retro"}


def test_household_memory_is_visible_confirmable_correctable_and_forgettable():
    complete_onboarding()
    memory = STATE.add_memory("pressure", "Made last week harder: Too many dishes", "Weekly retro", "suggested")
    response = client.post("/api/interactions", json={"action": "show_memory"})
    assert response.status_code == 200
    assert response.json()["view_id"] == "household-memory"

    confirmed = client.post("/api/interactions", json={"action": "confirm_memory", "target_id": memory["id"]})
    assert confirmed.status_code == 200
    assert memory["status"] == "confirmed"
    corrected = client.post("/api/interactions", json={"action": "update_memory", "target_id": memory["id"], "parameters": {"content": "Keep cleanup to one pan"}})
    assert corrected.status_code == 200
    assert memory["content"] == "Keep cleanup to one pan"
    forgotten = client.post("/api/interactions", json={"action": "forget_memory", "target_id": memory["id"]})
    assert forgotten.status_code == 200
    assert memory["active"] is False


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
    toast = next(item for item in first.json()["components"] if item["type"] == "toast")
    assert toast["actions"][0]["action"] == "undo_swap"
