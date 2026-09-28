from __future__ import annotations

import time
from typing import Any

import httpx
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .config import MCP_AUTH_SCOPES, Settings


class SupabaseTokenVerifier(TokenVerifier):
    """Validate Supabase access tokens without handling user passwords locally."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self.settings.supabase_configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    f"{self.settings.supabase_url.rstrip('/')}/auth/v1/user",
                    headers={
                        "apikey": self.settings.supabase_anon_key,
                        "Authorization": f"Bearer {token}",
                    },
                )
            if response.status_code != 200:
                return None
            user: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        user_id = str(user.get("id", ""))
        if not user_id:
            return None
        metadata = user.get("user_metadata") or {}
        app_metadata = user.get("app_metadata") or {}
        scopes = str(app_metadata.get("scope", " ".join(MCP_AUTH_SCOPES))).split()
        return AccessToken(
            token=token,
            client_id=str(app_metadata.get("client_id", "supabase-oauth")),
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
            subject=user_id,
            claims={"email": user.get("email"), "user_metadata": metadata},
        )
