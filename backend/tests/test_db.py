import httpx

from app.infrastructure.repositories import _repository_error


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
