"""Private friend circles. Sharing and discovery are deterministic, with no AI path."""

from typing import Any
from datetime import date

from .errors import ApplicationError, RepositoryError


class CircleService:
    def __init__(self, repository: Any):
        self.repository = repository

    @staticmethod
    def _raise_known_limit(exc: RepositoryError) -> None:
        if str(exc) in ("Circle limit reached", "Circle member limit reached",
                        "Daily share limit reached", "Comment rate limit reached"):
            raise ApplicationError(str(exc)) from exc
        raise exc

    async def list_circles(self) -> dict:
        items = await self.repository.circle_list()
        return {"items": items, "count": len(items)}

    async def create_circle(self, name: str) -> dict:
        clean = (name or "").strip()
        if not 1 <= len(clean) <= 80:
            raise ApplicationError("Enter a circle name of 1 to 80 characters")
        try:
            return await self.repository.circle_create(clean)
        except RepositoryError as exc:
            self._raise_known_limit(exc)

    async def invite_friend(self, circle_id: str, email: str) -> dict:
        clean = (email or "").strip().lower()
        if not clean or "@" not in clean or len(clean) > 320:
            raise ApplicationError("Enter an existing account email")
        try:
            return await self.repository.circle_invite(circle_id, clean)
        except RepositoryError as exc:
            if str(exc) in ("Existing friend account was not found", "Friend is already invited or a member"):
                raise ApplicationError(str(exc)) from exc
            self._raise_known_limit(exc)

    async def respond_invitation(self, circle_id: str, accept: bool) -> dict:
        return await self.repository.circle_respond(circle_id, accept)

    async def remove_friend(self, circle_id: str, user_id: str) -> dict:
        return await self.repository.circle_remove_friend(circle_id, user_id)

    async def leave_circle(self, circle_id: str) -> dict:
        return await self.repository.circle_leave(circle_id)

    async def list_shared_with_me(self, limit: int = 50, offset: int = 0, kind: str | None = None,
                                  circle_id: str | None = None) -> dict:
        if not 1 <= limit <= 100 or offset < 0 or kind not in (None, "week", "recipe", "meal", "message"):
            raise ApplicationError("Choose a valid share type, limit, and offset")
        if circle_id is not None:
            from uuid import UUID
            try:
                circle_id = str(UUID(circle_id))
            except (TypeError, ValueError):
                raise ApplicationError("Choose a valid circle") from None
        rows = await self.repository.circle_feed(limit + 1, offset, kind, circle_id)
        items = rows[:limit]
        return {"items": items, "count": len(items), "nextOffset": offset + limit if len(rows) > limit else None}

    async def get_shared_item(self, share_id: str) -> dict:
        return await self.repository.circle_get_post(share_id)

    async def share_week(self, circle_id: str, week_start: str, expected_audience: list[str] | None = None) -> dict:
        try:
            parsed = date.fromisoformat(week_start)
        except (TypeError, ValueError):
            raise ApplicationError("Choose a valid week start date") from None
        if parsed.weekday() != 0 or week_start != parsed.isoformat():
            raise ApplicationError("Choose a Monday week start date")
        try:
            return await self.repository.circle_share_week(circle_id, week_start, expected_audience)
        except RepositoryError as exc:
            self._raise_known_limit(exc)

    async def share_recipe(self, circle_id: str, recipe_id: str) -> dict:
        try:
            return await self.repository.circle_share_recipe(circle_id, recipe_id)
        except RepositoryError as exc:
            self._raise_known_limit(exc)

    async def send_message(self, circle_id: str, body: str, attachment_kind: str | None = None,
                           attachment_id: str | None = None, mention_ids: list[str] | None = None,
                           expected_audience: list[str] | None = None) -> dict:
        clean = (body or "").strip()
        if len(clean) > 2000 or (not clean and not attachment_kind):
            raise ApplicationError("Enter a message of 1 to 2000 characters")
        if (attachment_kind, bool(attachment_id)) not in ((None, False), ("recipe", True), ("meal", True)):
            raise ApplicationError("Choose one recipe or meal attachment")
        if len(mention_ids or []) > 25:
            raise ApplicationError("Mention at most 25 friends")
        try:
            return await self.repository.circle_send_message(circle_id, clean, attachment_kind, attachment_id,
                mention_ids or [], expected_audience)
        except RepositoryError as exc:
            self._raise_known_limit(exc)

    async def comment(self, share_id: str, body: str, target_type: str = "post", target_id: str | None = None,
                      mention_ids: list[str] | None = None) -> dict:
        clean = (body or "").strip()
        if not 1 <= len(clean) <= 2000:
            raise ApplicationError("Enter a comment of 1 to 2000 characters")
        if target_type not in ("post", "meal", "recipe"):
            raise ApplicationError("Choose the shared week, meal, or recipe to comment on")
        if len(mention_ids or []) > 25:
            raise ApplicationError("Mention at most 25 friends")
        try:
            return await self.repository.circle_comment(share_id, clean, target_type, target_id, mention_ids or [])
        except RepositoryError as exc:
            self._raise_known_limit(exc)

    async def save_shared_recipe(self, share_id: str, recipe_id: str) -> dict:
        return await self.repository.circle_save_recipe(share_id, recipe_id)

    async def delete_comment(self, comment_id: str) -> dict:
        return await self.repository.circle_delete_comment(comment_id)

    async def revoke_share(self, share_id: str) -> dict:
        return await self.repository.circle_revoke_post(share_id)

    async def list_direct_shares(self, limit: int = 50, offset: int = 0) -> dict:
        if not 1 <= limit <= 100 or offset < 0:
            raise ApplicationError("Choose a valid limit and offset")
        rows = await self.repository.direct_shares(limit + 1, offset)
        return {"items": rows[:limit], "count": min(len(rows), limit),
                "nextOffset": offset + limit if len(rows) > limit else None}

    async def mention_candidates(self, circle_id: str) -> dict:
        items = await self.repository.circle_mention_candidates(circle_id)
        return {"items": items, "count": len(items)}

    async def share_direct(self, email: str, kind: str, recipe_id: str | None = None,
                           week_start: str | None = None, meal_id: str | None = None) -> dict:
        clean = (email or "").strip().lower()
        if not clean or "@" not in clean or len(clean) > 320:
            raise ApplicationError("Enter an existing friend account email")
        if kind == "recipe" and recipe_id and not week_start and not meal_id:
            pass
        elif kind == "meal" and meal_id and not recipe_id and not week_start:
            pass
        elif kind == "week" and week_start and not recipe_id and not meal_id:
            try:
                parsed = date.fromisoformat(week_start)
            except (TypeError, ValueError):
                raise ApplicationError("Choose a valid week start date") from None
            if parsed.weekday() != 0 or parsed.isoformat() != week_start:
                raise ApplicationError("Choose a Monday week start date")
        else:
            raise ApplicationError("Choose one recipe or weekly plan")
        try:
            return await self.repository.direct_share(clean, kind, recipe_id, week_start, meal_id)
        except RepositoryError as exc:
            if str(exc) == "Existing friend account was not found":
                raise ApplicationError(str(exc)) from exc
            self._raise_known_limit(exc)
