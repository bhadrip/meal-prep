import httpx
import pytest

from app.application.errors import RepositoryError, StorageNotInstalledError
from app.config import Settings
from app.infrastructure.repositories import SupabaseRepository, _repository_error


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
