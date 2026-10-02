"""Private friend circles. Sharing and discovery are deterministic, with no AI path."""

from typing import Any
from datetime import date

from .errors import ApplicationError, RepositoryError


class CircleService:
    def __init__(self, repository: Any):
        self.repository = repository

    async def list_circles(self) -> dict:
        items = await self.repository.circle_list()
        return {"items": items, "count": len(items)}

    async def create_circle(self, name: str) -> dict:
        clean = (name or "").strip()
        if not 1 <= len(clean) <= 80:
            raise ApplicationError("Enter a circle name of 1 to 80 characters")
        return await self.repository.circle_create(clean)

    async def invite_friend(self, circle_id: str, email: str) -> dict:
        clean = (email or "").strip().lower()
        if not clean or "@" not in clean or len(clean) > 320:
            raise ApplicationError("Enter an existing account email")
        try:
            return await self.repository.circle_invite(circle_id, clean)
        except RepositoryError as exc:
            if str(exc) in ("Existing friend account was not found", "Friend is already invited or a member"):
                raise ApplicationError(str(exc)) from exc
            raise

    async def respond_invitation(self, circle_id: str, accept: bool) -> dict:
        return await self.repository.circle_respond(circle_id, accept)

    async def remove_friend(self, circle_id: str, user_id: str) -> dict:
        return await self.repository.circle_remove_friend(circle_id, user_id)

    async def leave_circle(self, circle_id: str) -> dict:
        return await self.repository.circle_leave(circle_id)

    async def list_shared_with_me(self, limit: int = 50, offset: int = 0, kind: str | None = None) -> dict:
        if not 1 <= limit <= 100 or offset < 0 or kind not in (None, "week", "recipe"):
            raise ApplicationError("Choose a valid share type, limit, and offset")
        rows = await self.repository.circle_feed(limit + 1, offset, kind)
        items = rows[:limit]
        return {"items": items, "count": len(items), "nextOffset": offset + limit if len(rows) > limit else None}

    async def get_shared_item(self, share_id: str) -> dict:
        return await self.repository.circle_get_post(share_id)

    async def share_week(self, circle_id: str, week_start: str) -> dict:
        try:
            parsed = date.fromisoformat(week_start)
        except (TypeError, ValueError):
            raise ApplicationError("Choose a valid week start date") from None
        if parsed.weekday() != 0 or week_start != parsed.isoformat():
            raise ApplicationError("Choose a Monday week start date")
        return await self.repository.circle_share_week(circle_id, week_start)

    async def share_recipe(self, circle_id: str, recipe_id: str) -> dict:
        return await self.repository.circle_share_recipe(circle_id, recipe_id)

    async def comment(self, share_id: str, body: str, target_type: str = "post", target_id: str | None = None) -> dict:
        clean = (body or "").strip()
        if not 1 <= len(clean) <= 2000:
            raise ApplicationError("Enter a comment of 1 to 2000 characters")
        if target_type not in ("post", "meal", "recipe"):
            raise ApplicationError("Choose the shared week, meal, or recipe to comment on")
        return await self.repository.circle_comment(share_id, clean, target_type, target_id)

    async def save_shared_recipe(self, share_id: str, recipe_id: str) -> dict:
        return await self.repository.circle_save_recipe(share_id, recipe_id)

    async def revoke_share(self, share_id: str) -> dict:
        return await self.repository.circle_revoke_post(share_id)
