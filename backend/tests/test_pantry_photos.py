from io import BytesIO

import pytest
from PIL import Image

from app.application.errors import ApplicationError
from app.application.pantry_photos import _trusted_file_url, compact_photo, normalize_observations
from app.application.services import RecipePantryService
from app.infrastructure.repositories import DemoRepository


def test_compact_photo_strips_metadata_and_limits_dimensions():
    image = Image.new("RGB", (2400, 1200), "red")
    raw = BytesIO()
    image.save(raw, "JPEG", quality=95, exif=Image.Exif())
    compact, width, height = compact_photo(raw.getvalue())
    assert (width, height) == (1600, 800)
    assert len(compact) < len(raw.getvalue())
    with Image.open(BytesIO(compact)) as saved:
        assert saved.format == "WEBP"
        assert not saved.getexif()


def test_photo_inputs_reject_untrusted_urls_and_invented_exact_counts():
    assert _trusted_file_url("https://files.oaiusercontent.com/photo?id=1")
    assert not _trusted_file_url("http://169.254.169.254/latest/meta-data")
    assert not _trusted_file_url("https://openai.com.attacker.test/photo")
    with pytest.raises(ApplicationError, match="exact"):
        normalize_observations([{"name": "Milk", "quantityConfidence": "exact"}], "fridge")


@pytest.mark.asyncio
async def test_photo_capture_then_apply_preserves_reviewable_evidence(monkeypatch):
    raw = BytesIO()
    Image.new("RGB", (40, 30), "blue").save(raw, "PNG")

    async def fake_download(_file):
        return raw.getvalue()

    monkeypatch.setattr("app.application.services.download_chatgpt_photo", fake_download)
    repository = DemoRepository()
    repository._pantry_photos = []
    repository._pantry = []
    service = RecipePantryService(repository)
    captured = await service.save_pantry_photo(
        {"download_url": "https://files.oaiusercontent.com/photo", "file_id": "file_123"},
        [{"name": "Milk", "quantity": 1, "unit": "carton"}],
        apply_to_pantry=False,
    )
    assert captured["status"] == "captured"
    assert await repository.get_pantry() == []
    applied = await service.apply_pantry_photo(captured["id"])
    assert applied["status"] == "applied"
    assert len(applied["applied_item_ids"]) == 1
    assert (await service.get_pantry_photos())[0]["observations"][0]["name"] == "Milk"
    assert (await repository.get_pantry())[0]["provenance"]["evidenceId"] == captured["id"]
