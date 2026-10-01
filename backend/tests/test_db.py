import httpx
import pytest
from unittest.mock import AsyncMock

from app.application.errors import RepositoryError, RevisionConflictError, StorageNotInstalledError
from app.config import Settings
from app.infrastructure.repositories import SupabaseRepository, _repository_error


@pytest.mark.asyncio
async def test_rule_reads_scope_to_active_household_and_saves_send_expected_revision(monkeypatch):
    repository = SupabaseRepository(Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None), "token")
    monkeypatch.setattr(repository, "household_id", AsyncMock(return_value="active-household"))
    read = AsyncMock(return_value=[{"id": "revision-id", "revision": 1, "text": "Saturday pasta.", "created_at": "now"}])
    monkeypatch.setattr(repository, "request", read)
    assert (await repository.get_meal_plan_rules())["text"] == "Saturday pasta."
    assert read.call_args.kwargs["params"]["household_id"] == "eq.active-household"
    await repository.get_meal_plan_rules("revision-id")
    assert read.call_args.kwargs["params"]["id"] == "eq.revision-id"
    rpc = AsyncMock(return_value={"revision": 2})
    monkeypatch.setattr(repository, "rpc", rpc)
    assert await repository.save_meal_plan_rules("Saturday stir-fry.", 1) == {"revision": 2}
    rpc.assert_awaited_once_with("save_meal_plan_rules", {"rule_text": "Saturday stir-fry.", "expected_revision": 1})


def test_rule_conflict_maps_to_a_recoverable_error_and_missing_storage_is_explicit():
    request = httpx.Request("POST", "https://example.supabase.co/rest/v1/rpc/save_meal_plan_rules")
    response = httpx.Response(400, request=request, json={"code": "P0001", "message": "Meal plan rules changed. Reload the current rules before saving."})
    mapped = _repository_error("rpc/save_meal_plan_rules", httpx.HTTPStatusError("conflict", request=request, response=response))
    assert isinstance(mapped, RevisionConflictError)
    missing = httpx.Response(404, request=request, json={"code": "PGRST202", "message": "Missing function"})
    assert isinstance(_repository_error("rpc/save_meal_plan_rules", httpx.HTTPStatusError("missing", request=request, response=missing)), StorageNotInstalledError)


@pytest.mark.asyncio
async def test_pantry_category_is_written_to_supabase_row(monkeypatch):
    repository = SupabaseRepository(Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None), "token")
    monkeypatch.setattr(repository, "household_id", AsyncMock(return_value="household-id"))
    writes = []

    async def request(method, path, **kwargs):
        writes.append((method, path, kwargs))
        return [kwargs["json"]]

    monkeypatch.setattr(repository, "request", request)
    saved = await repository.update_pantry_item({"name": "Garlic paste", "category": "condiments", "quantity": 1})
    assert saved["category"] == "condiments"
    assert writes[0][1] == "pantry_items"
    assert writes[0][2]["json"]["category"] == "condiments"


def test_missing_planning_table_has_actionable_error():
    request = httpx.Request("GET", "https://example.supabase.co/rest/v1/weekly_schedules")
    response = httpx.Response(
        404,
        request=request,
        json={
            "code": "PGRST205",
            "message": "Could not find the table 'public.weekly_schedules' in the schema cache",
        },
    )
    error = httpx.HTTPStatusError("not found", request=request, response=response)

    mapped = _repository_error("weekly_schedules", error)

    assert str(mapped) == (
        "Weekly schedules storage is not installed. "
        "Apply the checked-in Supabase migrations before using this feature."
    )


def test_missing_feedback_table_has_actionable_error():
    request = httpx.Request("GET", "https://example.supabase.co/rest/v1/feedback_entries")
    response = httpx.Response(
        404,
        request=request,
        json={
            "code": "PGRST205",
            "message": "Could not find the table 'public.feedback_entries' in the schema cache",
        },
    )
    error = httpx.HTTPStatusError("not found", request=request, response=response)

    mapped = _repository_error("feedback_entries", error)

    assert str(mapped) == (
        "Feedback storage is not installed. "
        "Apply the checked-in Supabase migrations before using this feature."
    )


def test_missing_feedback_rpc_has_actionable_error():
    request = httpx.Request(
        "POST", "https://example.supabase.co/rest/v1/rpc/get_experience_feedback"
    )
    response = httpx.Response(
        404,
        request=request,
        json={
            "code": "PGRST202",
            "message": "Could not find the function public.get_experience_feedback",
        },
    )
    error = httpx.HTTPStatusError("not found", request=request, response=response)

    mapped = _repository_error("rpc/get_experience_feedback", error)

    assert isinstance(mapped, StorageNotInstalledError)
    assert mapped.feature == "feedback"
    assert str(mapped) == (
        "Feedback storage is not installed. "
        "Apply the checked-in Supabase migrations before using this feature."
    )


@pytest.mark.asyncio
async def test_dashboard_preference_write_uses_active_context_and_saved_row(monkeypatch):
    repository = SupabaseRepository(
        Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None),
        "token",
    )
    context = {"householdId": "active-id", "planningPreferences": {"weeknightMaxMinutes": 30}}
    saved = {"weeknightMaxMinutes": 30, "dashboard": {"hiddenCards": ["pantry"]}}
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return [{"planning_preferences": saved}]

    monkeypatch.setattr(repository, "request", request)
    result = await repository.update_household_preferences(
        {"planningPreferences": saved}, context=context
    )
    assert result["planningPreferences"] == saved
    assert calls[0][2]["params"] == {"household_id": "eq.active-id"}
    assert len(calls) == 1

    async def empty_update(method, path, **kwargs):
        return []

    monkeypatch.setattr(repository, "request", empty_update)
    with pytest.raises(RepositoryError, match="were not saved"):
        await repository.update_household_preferences({"planningPreferences": saved}, context=context)


@pytest.mark.asyncio
async def test_household_lookup_is_reused_within_one_request(monkeypatch):
    repository = SupabaseRepository(
        Settings(supabase_url="https://example.supabase.co", supabase_anon_key="test", _env_file=None),
        "token",
    )
    calls = []

    async def rpc(name, payload=None):
        calls.append(name)
        return {"householdId": "active-id", "planningPreferences": {}}

    monkeypatch.setattr(repository, "rpc", rpc)
    first = await repository.get_household_context()
    first["planningPreferences"]["dashboard"] = {"hiddenCards": ["pantry"]}
    assert await repository.household_id() == "active-id"
    assert "dashboard" not in (await repository.get_household_context())["planningPreferences"]
    assert calls == ["get_household_context"]
