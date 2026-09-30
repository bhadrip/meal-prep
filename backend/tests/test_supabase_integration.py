"""Roundtrip checks against a disposable local Supabase stack."""

import os
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.infrastructure.repositories import SupabaseRepository


@pytest.mark.asyncio
async def test_local_supabase_week_plan_and_rhythm_roundtrip():
    url = os.environ.get("MEAL_PREP_TEST_SUPABASE_URL")
    anon_key = os.environ.get("MEAL_PREP_TEST_ANON_KEY")
    service_key = os.environ.get("MEAL_PREP_TEST_SERVICE_ROLE_KEY")
    if not all((url, anon_key, service_key)):
        pytest.skip("local Supabase test credentials are not configured")

    email = f"meal-prep-plan-{uuid4()}@example.test"
    password = str(uuid4())
    admin_headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    async with httpx.AsyncClient(base_url=url, timeout=20) as client:
        created = await client.post("/auth/v1/admin/users", headers=admin_headers, json={
            "email": email, "password": password, "email_confirm": True,
        })
        assert created.status_code in (200, 201), created.text
        user_id = created.json()["id"]
        household_id = None
        try:
            signed_in = await client.post(
                "/auth/v1/token", params={"grant_type": "password"},
                headers={"apikey": anon_key}, json={"email": email, "password": password},
            )
            assert signed_in.status_code == 200, signed_in.text
            repository = SupabaseRepository(
                Settings(supabase_url=url, supabase_anon_key=anon_key, auth_required=True),
                signed_in.json()["access_token"],
            )
            household_id = (await repository.get_household_context())["householdId"]

            first_week = "2030-02-04"
            second_week = "2030-02-11"
            first = await repository.save_meal_plan({
                "weekStart": first_week, "status": "draft",
                "entries": [{"date": first_week, "slot": "dinner", "meal": "Lentil bowls"}],
            })
            assert first["entries"][0]["meal"] == "Lentil bowls"
            second = await repository.save_meal_plan({
                "weekStart": second_week, "status": "draft",
                "entries": [{"date": second_week, "slot": "breakfast", "meal": "Oatmeal"}],
            })
            assert second["entries"][0]["meal"] == "Oatmeal"
            assert (await repository.get_meal_plan(first_week))["id"] == first["id"]
            assert (await repository.get_meal_plan(second_week))["id"] == second["id"]

            edited = await repository.save_meal_plan({
                "id": second["id"], "weekStart": second_week, "status": "draft",
                "entries": [{"date": second_week, "slot": "breakfast", "meal": "Yogurt bowls"}],
            })
            assert edited["entries"][0]["meal"] == "Yogurt bowls"
            assert (await repository.get_meal_plan(first_week))["entries"][0]["meal"] == "Lentil bowls"

            days = [{"day": day, "mode": "quick"} for day in (
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
            )]
            assert (await repository.save_weekly_schedule({"weekStart": second_week, "days": days}))["days"] == days
            days[0]["mode"] = "busy"
            assert (await repository.save_weekly_schedule({"weekStart": second_week, "days": days}))["days"][0]["mode"] == "busy"
        finally:
            if household_id:
                removed = await client.delete(
                    "/rest/v1/households", params={"id": f"eq.{household_id}"},
                    headers={**admin_headers, "Prefer": "return=representation"},
                )
                assert removed.status_code in (200, 204), removed.text
            deleted = await client.delete(f"/auth/v1/admin/users/{user_id}", headers=admin_headers)
            assert deleted.status_code in (200, 204), deleted.text
