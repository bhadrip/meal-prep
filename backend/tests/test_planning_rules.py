from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.application.errors import ApplicationError, RevisionConflictError
from app.application.services import FeedbackService, PlanningService
from app.infrastructure.repositories import DemoRepository, demo_repository
from app.main import app


@pytest.mark.asyncio
async def test_english_rules_are_immutable_and_stale_edits_fail():
    service = PlanningService(DemoRepository())
    assert await service.get_rules() is None
    first = await service.save_rules("  Saturday pasta.\nReuse it Monday.  ", 0)
    second = await service.save_rules("Saturday stir-fry.", 1)
    assert second["revision"] == 2
    assert (await service.get_rules(first["id"]))["text"] == "Saturday pasta.\nReuse it Monday."
    assert await service.get_rule_history() == [second, first]
    with pytest.raises(RevisionConflictError, match="changed"):
        await service.save_rules("Overwrite another edit", 1)
    assert await service.get_rules() == second
    assert await service.save_rules(second["text"], 2) == second
    cleared = await service.save_rules(" ", 2)
    assert cleared["text"] == "" and cleared["revision"] == 3
    for text, revision in [(None, 3), ("x" * 10001, 3), ("Valid", -1), ("Valid", True)]:
        with pytest.raises(ApplicationError):
            await service.save_rules(text, revision)
    with pytest.raises(ApplicationError, match="not found"):
        await service.get_rules(str(uuid4()))
    with pytest.raises(ApplicationError, match="between"):
        await service.get_rule_history(0)
    assert len(await service.get_rule_history()) == 3


@pytest.mark.asyncio
async def test_context_uses_prior_weeks_and_keeps_notes_in_their_week():
    repository = DemoRepository()
    repository._meal_plans = {}
    service = PlanningService(repository)
    rules = await service.save_rules("Rotate rasam variations; leftovers are welcome.", 0)
    for week in ["2030-01-14", "2030-01-21", "2030-01-28", "2030-02-04", "2030-02-11"]:
        await service.save_meal_plan({"weekStart": week, "entries": [
            {"date": week, "slot": "dinner", "meal": f"Meal {week}"},
        ]})
    days = [{"day": name, "mode": "flexible"} for name in (
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    )]
    await service.save_schedule({"weekStart": "2030-02-04", "days": days, "notes": "Guests Saturday; use spinach."})
    await service.save_schedule({"weekStart": "2030-02-11", "days": days, "notes": "A normal week."})
    await FeedbackService(repository).save({"weekStart": "2030-01-28", "feedbackType": "worked_well",
        "note": "Lemon rasam worked well.", "nextTime": "Serve chilli separately."})
    context = await service.get_context("2030-02-04")
    assert context["mealPlanRules"] == rules
    assert context["mealPlan"]["weekStart"] == "2030-02-04"
    assert [p["weekStart"] for p in context["recentPlans"]] == ["2030-01-28", "2030-01-21"]
    assert context["schedule"]["notes"] == "Guests Saturday; use spinach."
    assert any(item["next_time"] == "Serve chilli separately." for item in context["feedback"])
    assert context["pantry"] and context["recipeTags"]
    empty = await service.get_context("2030-02-18")
    assert empty["schedule"] is None and empty["mealPlan"] is None
    assert (await service.get_context("2030-02-11"))["schedule"]["notes"] == "A normal week."
    with pytest.raises(ApplicationError, match="ISO date"):
        await service.get_context("invalid")
    with pytest.raises(ApplicationError, match="Monday"):
        await service.get_context("2030-02-05")
    with pytest.raises(ApplicationError, match="Week notes"):
        await service.save_schedule({"weekStart": "2030-02-04", "days": days, "notes": 123})


@pytest.mark.asyncio
async def test_plans_keep_the_rule_revision_used_on_manual_edits():
    service = PlanningService(DemoRepository())
    rules = await service.save_rules("Saturday pasta.", 0)
    saved = await service.save_meal_plan({"weekStart": "2030-02-04", "ruleRevisionId": rules["id"],
        "entries": [{"date": "2030-02-04", "slot": "dinner", "meal": "Pasta leftovers"}]})
    await service.save_rules("Saturday stir-fry.", 1)
    edited = await service.save_meal_plan({"id": saved["id"], "weekStart": "2030-02-04",
        "entries": [{"date": "2030-02-04", "slot": "dinner", "meal": "Changed dinner"}]})
    assert edited["ruleRevision"] == rules and edited["ruleRevisionId"] == rules["id"]
    with pytest.raises(ApplicationError, match="not found"):
        await service.save_meal_plan({**edited, "ruleRevisionId": str(uuid4())})
    assert (await service.get_meal_plan("2030-02-04"))["ruleRevision"] == rules


def test_http_rules_roundtrip_and_conflicts_do_not_overwrite():
    demo_repository.cache_clear()
    try:
        client = TestClient(app)
        assert client.get("/api/meal-plan-rules").json() == {"rules": None}
        first = client.put("/api/meal-plan-rules", json={"text": "Saturday pasta.", "expectedRevision": 0}).json()
        second = client.put("/api/meal-plan-rules", json={"text": "Saturday stir-fry.", "expectedRevision": 1}).json()
        stale = client.put("/api/meal-plan-rules", json={"text": "Stale edit", "expectedRevision": 1})
        assert stale.status_code == 409 and "changed" in stale.json()["detail"]
        assert client.get("/api/meal-plan-rules").json()["rules"] == second
        assert client.get(f"/api/meal-plan-rules?revision_id={first['id']}").json()["rules"] == first
        assert client.get("/api/meal-plan-rules/history").json()["items"] == [second, first]
        assert client.put("/api/meal-plan-rules", json={"text": {}, "expectedRevision": 2}).status_code == 422
        assert client.get("/api/meal-plan-rules/history?limit=0").status_code == 422
        context = client.get("/api/planning-context?week_start=2030-02-04").json()
        assert context["mealPlanRules"] == second and context["mealPlan"] is None
        assert client.get("/api/app/snapshot").json()["sections"]["mealPlanRules"]["value"] == second
    finally:
        demo_repository.cache_clear()


def test_rule_viewer_reads_the_plan_revision_and_rejects_unavailable_versions():
    demo_repository.cache_clear()
    try:
        client = TestClient(app)
        original = client.put("/api/meal-plan-rules", json={
            "text": "Saturday pasta.", "expectedRevision": 0,
        }).json()
        client.put("/api/meal-plan", json={
            "weekStart": "2030-02-04", "ruleRevisionId": original["id"],
            "entries": [{"date": "2030-02-04", "slot": "dinner", "meal": "Pasta"}],
        }).raise_for_status()
        current = client.put("/api/meal-plan-rules", json={
            "text": "Saturday stir-fry.", "expectedRevision": 1,
        }).json()
        plan = client.get("/api/meal-plan?week_start=2030-02-04").json()["plan"]
        preview = client.get(f"/api/meal-plan-rules?revision_id={plan['ruleRevisionId']}")
        assert preview.status_code == 200 and preview.json()["rules"] == original
        assert preview.json()["rules"] != current
        for revision_id, message in [(str(uuid4()), "not found"), ("invalid", "Invalid")]:
            failed = client.get("/api/meal-plan-rules", params={"revision_id": revision_id})
            assert failed.status_code == 422 and message in failed.json()["detail"]
        assert client.get("/api/meal-plan-rules").json()["rules"] == current
        assert client.get("/api/meal-plan?week_start=2030-02-04").json()["plan"] == plan
    finally:
        demo_repository.cache_clear()


def test_week_note_edit_preserves_rhythm_rules_and_rejects_an_oversized_draft():
    demo_repository.cache_clear()
    try:
        client = TestClient(app)
        rules = client.put("/api/meal-plan-rules", json={
            "text": "Cook ambta baaji on Saturday.", "expectedRevision": 0,
        }).json()
        rhythm = {"weekStart": "2030-02-04", "isNormalWeek": False, "rememberRhythm": False,
            "days": [{"day": day, "mode": "busy" if day == "Monday" else "leftovers"}
                for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]}
        original = client.put("/api/schedule", json=rhythm).json()
        failed = client.put("/api/schedule", json={**rhythm, "notes": "x" * 3001})
        assert failed.status_code == 422 and "Week notes" in failed.json()["detail"]
        assert client.get("/api/schedule?week_start=2030-02-04").json()["schedule"] == original
        saved = client.put("/api/schedule", json={**rhythm, "notes": "Guests Saturday; use spinach."}).json()
        assert saved["days"] == original["days"]
        assert saved["is_normal_week"] is False and saved["remember_rhythm"] is False
        context = client.get("/api/planning-context?week_start=2030-02-04").json()
        assert context["schedule"]["notes"] == saved["notes"]
        assert context["mealPlanRules"] == rules
        assert client.get("/api/meal-plan-rules/history").json()["items"] == [rules]
        changed_rhythm = {**rhythm, "days": [{**day, "mode": "quick"} for day in rhythm["days"]]}
        changed = client.put("/api/schedule", json=changed_rhythm).json()
        assert changed["notes"] == saved["notes"] and changed["id"] == saved["id"]
        assert all(day["mode"] == "quick" for day in changed["days"])
    finally:
        demo_repository.cache_clear()
