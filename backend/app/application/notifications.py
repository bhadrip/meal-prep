"""Personal inbox operations shared by HTTP and direct MCP clients."""
from datetime import UTC, datetime
from uuid import UUID

from ..infrastructure.repositories import SupabaseRepository


async def list_inbox(repository, archived: bool = False) -> dict:
    if not isinstance(repository, SupabaseRepository):
        return {"items": [], "unreadCount": 0}
    rows = await repository.request("GET", "notifications", params={
        "select": "id,household_id,kind,title,target_path,created_at,read_at,archived_at",
        "archived_at": "not.is.null" if archived else "is.null",
        "order": "created_at.desc", "limit": "100",
    }) or []
    return {"items": rows, "unreadCount": sum(not row.get("read_at") and not row.get("archived_at") for row in rows)}


async def update_inbox(repository, notification_id: str, field: str, enabled: bool) -> dict:
    notification_id = str(UUID(notification_id))
    if field not in {"read_at", "archived_at"}:
        raise ValueError("Unsupported notification state")
    if not isinstance(repository, SupabaseRepository):
        raise ValueError("Notification not found")
    rows = await repository.request("PATCH", "notifications",
        params={"id": f"eq.{notification_id}"},
        json={field: datetime.now(UTC).isoformat() if enabled else None}) or []
    if not rows:
        raise ValueError("Notification not found")
    return {"id": rows[0]["id"], "readAt" if field == "read_at" else "archivedAt": rows[0][field]}
