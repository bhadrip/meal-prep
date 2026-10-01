"""Planning reminders from recorded dates, never inferred expiry dates."""
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

from .pantry_categories import infer_pantry_category


def pantry_freshness(item: dict, today: date | None = None) -> dict:
    today = today or datetime.now(ZoneInfo("America/Los_Angeles")).date()
    def read_date(value):
        try:
            return date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None

    purchased = read_date(item.get("acquiredAt", item.get("acquired_at")))
    source = "Recorded purchase date" if purchased else None
    if purchased is None:
        match = re.search(r"\bpurchased\s+(\d{4}-\d{2}-\d{2})\b", item.get("freshnessBasis", item.get("freshness_basis")) or "", re.I)
        purchased = read_date(match[1]) if match else None
        source = "Purchase date from receipt evidence" if purchased else None
    age = (today - purchased).days if purchased and purchased <= today else None
    use_by = read_date(item.get("useByDate", item.get("use_by_date")))
    days = (use_by - today).days if use_by else None
    category = item.get("category") or "uncategorized"
    if category == "uncategorized":
        category = infer_pantry_category(item.get("name", ""))
    produce = category in {"fruits", "vegetables"} and item.get("storageLocation", item.get("storage_location")) != "freezer"
    status = "undated"
    if days is not None:
        status = "past_date" if days < 0 else "due_soon" if days <= 2 else "dated"
    elif produce:
        status = "review_age" if age is not None and age >= 7 else "age_known" if age is not None else "age_unknown"
    if item.get("quantity") == 0:
        status = "finished"
    return {"status": status, "ageDays": age, "purchaseDate": purchased.isoformat() if age is not None else None,
            "source": source if age is not None else None, "useByDate": use_by.isoformat() if use_by else None,
            "daysUntilUseBy": days, "isProduce": produce}
