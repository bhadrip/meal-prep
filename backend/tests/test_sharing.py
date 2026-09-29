from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest

from app.application.services import RecipePantryService
from app.infrastructure.repositories import DemoRepository
from app.main import app
from app.sharing import render_shared_recipe_page


RECIPE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_recipe_share_is_a_private_data_free_snapshot_and_copy():
    repository = DemoRepository()
    service = RecipePantryService(repository)
    repository._recipes = [{**repository._recipes[0], "private_note": "Family secret"}]
    share = await service.create_recipe_share(RECIPE_ID)
    token = share["token"]
    published = DemoRepository.read_shared_recipe(token)
    assert published["recipe"]["title"] == "Paneer rice bowls"
    assert "Family secret" not in str(published)
    assert "householdId" not in str(published)
    public_response = TestClient(app).get(f"/s/{token}")
    assert public_response.status_code == 200
    assert "Paneer rice bowls" in public_response.text
    assert "Family secret" not in public_response.text
    assert public_response.headers["cache-control"] == "no-store"

    await repository.save_recipe({"id": RECIPE_ID, "title": "Changed original"})
    assert DemoRepository.read_shared_recipe(token)["recipe"]["title"] == "Paneer rice bowls"
    copied_id = (await service.copy_shared_recipe(token))["recipeId"]
    assert copied_id != RECIPE_ID
    assert (await repository.get_recipe(copied_id))["title"] == "Paneer rice bowls"

    assert (await service.revoke_recipe_share(share["id"]))["revoked"]
    assert DemoRepository.read_shared_recipe(token) is None
    assert TestClient(app).get(f"/s/{token}").status_code == 404


@pytest.mark.asyncio
async def test_expired_recipe_share_cannot_be_opened():
    repository = DemoRepository()
    share = await repository.create_recipe_share(
        RECIPE_ID, (datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    repository._shares[share["token"]]["expiresAt"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert DemoRepository.read_shared_recipe(share["token"]) is None


def test_public_page_escapes_recipe_content_and_link_lifecycle():
    html = render_shared_recipe_page({"recipe": {
        "title": "<script>alert(1)</script>",
        "description": "A <b>recipe</b>",
        "ingredients": [{"name": "<img src=x onerror=alert(1)>"}],
        "instructions": ["Cook carefully"],
    }})
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html
    assert "<script>alert(1)</script>" not in html

    assert TestClient(app).get("/s/not-a-token").status_code == 404
