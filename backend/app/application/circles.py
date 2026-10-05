"""Private friend circles. Sharing and discovery are deterministic, with no AI path."""

from typing import Any
from datetime import date, datetime
from uuid import UUID
import base64

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
                           expected_audience: list[str] | None = None, client_id: str | None = None,
                           reply_to: str | None = None) -> dict:
        clean = (body or "").strip()
        if len(clean) > 2000 or (not clean and not attachment_kind):
            raise ApplicationError("Enter a message of 1 to 2000 characters")
        if (attachment_kind, bool(attachment_id)) not in ((None, False), ("recipe", True), ("meal", True)):
            raise ApplicationError("Choose one recipe or meal attachment")
        if len(mention_ids or []) > 25:
            raise ApplicationError("Mention at most 25 friends")
        try:
            if client_id is not None:
                self._uuid(client_id)
            if reply_to is not None:
                self._uuid(reply_to)
            return await self.repository.chat_send(circle_id, clean, attachment_kind, attachment_id,
                mention_ids or [], expected_audience, client_id, reply_to)
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

    @staticmethod
    def _uuid(value):
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError):
            raise ApplicationError("Choose a valid identifier") from None

    async def conversations(self) -> dict:
        return {"items": await self.repository.chat_rooms()}

    async def history(self, circle_id: str, limit: int = 50, cursor: str | None = None,
                      query: str = "", sender: str | None = None, date_from: str | None = None,
                      kind: str | None = None) -> dict:
        self._uuid(circle_id)
        if not 1 <= limit <= 100 or len(query) > 120 or kind not in (None, "message", "recipe", "meal", "week"):
            raise ApplicationError("Choose valid history filters")
        if sender and not (hasattr(self.repository, "_chat")): self._uuid(sender)
        if date_from:
            try: date.fromisoformat(date_from)
            except ValueError: raise ApplicationError("Choose a valid date") from None
        boundary = None
        if cursor:
            try:
                boundary = base64.urlsafe_b64decode(cursor.encode()).decode()
                stamp, post_id = boundary.rsplit("|", 1)
                datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                UUID(post_id)
            except (ValueError, UnicodeError, TypeError):
                raise ApplicationError("History cursor is invalid") from None
        rows = await self.repository.chat_history(circle_id, limit + 1, boundary, query.strip(), sender, date_from, kind)
        items = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(f"{items[-1]['createdAt']}|{items[-1]['id']}".encode()).decode() if len(rows)>limit else None
        return {"items": items, "nextCursor": next_cursor}

    async def update_conversation(self, circle_id: str, last_read_id: str | None = None,
                                  muted: bool | None = None) -> dict:
        self._uuid(circle_id)
        if muted is not None and not isinstance(muted, bool): raise ApplicationError("Choose a valid mute setting")
        if last_read_id: self._uuid(last_read_id)
        if last_read_id is None and muted is None:
            raise ApplicationError("Choose a read position or mute setting")
        return await self.repository.chat_action("state", circle_id, {"lastReadId": last_read_id, "muted": muted})

    async def edit_message(self, message_id: str, body: str) -> dict:
        self._uuid(message_id)
        if not isinstance(body, str): raise ApplicationError("Enter a text message")
        body = body.strip()
        if not 1 <= len(body) <= 2000: raise ApplicationError("Enter a message of 1 to 2000 characters")
        return await self.repository.chat_action("edit", message_id, {"body": body})

    async def react(self, message_id: str, emoji: str, active: bool = True) -> dict:
        self._uuid(message_id)
        if not isinstance(active, bool): raise ApplicationError("Choose a valid reaction state")
        if emoji not in ("👍", "❤️", "😋", "🎉"):
            raise ApplicationError("Choose a supported reaction")
        return await self.repository.chat_action("reaction", message_id, {"emoji": emoji, "active": active})

    async def profile(self, name: str | None = None) -> dict:
        if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 60):
            raise ApplicationError("Enter a display name of 1 to 60 characters")
        return await self.repository.chat_profile(name.strip() if name is not None else None)

    async def sync(self) -> dict:
        return await self.repository.chat_sync()
