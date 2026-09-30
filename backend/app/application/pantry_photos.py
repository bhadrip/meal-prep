"""Capture small, reviewable photo evidence for pantry changes."""

from __future__ import annotations

from io import BytesIO
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import ApplicationError


MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 24_000_000
MAX_SIDE = 1600


def _trusted_file_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
        and (
            host == "chatgpt.com"
            or host.endswith(".chatgpt.com")
            or host == "openai.com"
            or host.endswith(".openai.com")
            or host == "oaiusercontent.com"
            or host.endswith(".oaiusercontent.com")
        )
    )


async def download_chatgpt_photo(file: dict[str, str]) -> bytes:
    url = file.get("download_url", "")
    if not file.get("file_id") or not _trusted_file_url(url):
        raise ApplicationError("A ChatGPT photo file is required")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for _ in range(3):
            if not _trusted_file_url(url):
                raise ApplicationError("The photo download URL is not trusted")
            try:
                async with client.stream("GET", url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ApplicationError("The photo download redirect is invalid")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    if int(response.headers.get("content-length", "0")) > MAX_DOWNLOAD_BYTES:
                        raise ApplicationError("The photo is too large (15 MB maximum)")
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise ApplicationError("The photo is too large (15 MB maximum)")
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.HTTPError as exc:
                raise ApplicationError("Could not download the ChatGPT photo") from exc
    raise ApplicationError("The photo has too many redirects")


def compact_photo(data: bytes) -> tuple[bytes, int, int]:
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ApplicationError("The photo has too many pixels")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=72, method=4)
            return output.getvalue(), image.width, image.height
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ApplicationError("The file is not a supported photo (JPEG, PNG, or WebP)") from exc


def normalize_observations(items: list[dict], storage_location: str) -> list[dict]:
    if not isinstance(items, list) or len(items) > 50:
        raise ApplicationError("observed_items must contain at most 50 items")
    result = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ApplicationError("Every observed item needs a name")
        name = item["name"].strip()
        if not 1 <= len(name) <= 160:
            raise ApplicationError("Observed item names must be 1 to 160 characters")
        quantity = item.get("quantity")
        if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0):
            raise ApplicationError("Observed quantities must be positive numbers or omitted")
        confidence = item.get("quantityConfidence", "estimated" if quantity is not None else "unknown")
        if confidence not in ("estimated", "unknown"):
            raise ApplicationError("Photo quantities cannot be marked exact")
        item_id = item.get("id")
        if item_id is not None:
            try:
                UUID(str(item_id))
            except ValueError as exc:
                raise ApplicationError("An observed item ID must be a UUID") from exc
        result.append({
            "name": name,
            "quantity": quantity,
            "unit": str(item.get("unit") or "").strip()[:40] or None,
            "storageLocation": str(item.get("storageLocation") or storage_location).strip()[:80],
            "quantityConfidence": confidence,
            "id": str(item_id) if item_id is not None else str(uuid4()),
        })
    return result
