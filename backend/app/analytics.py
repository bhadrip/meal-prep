"""Small, privacy-limited PostHog event capture shared by HTTP and MCP."""

from __future__ import annotations

import hashlib
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID, uuid4

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import get_settings


logger = logging.getLogger(__name__)
_request: ContextVar[RequestTelemetry | None] = ContextVar("meal_prep_analytics_request", default=None)
_verified_user: ContextVar[str | None] = ContextVar("meal_prep_analytics_user", default=None)
_SAFE_CLIENTS = {"web", "ios"}


@dataclass(frozen=True)
class RequestTelemetry:
    entry_point: str
    request_id: str
    session_id: str | None = None


def request_telemetry() -> RequestTelemetry | None:
    return _request.get()


def set_verified_user(user_id: str) -> None:
    _verified_user.set(user_id)


def _session_id(headers: dict[bytes, bytes], entry_point: str) -> str | None:
    if entry_point == "mcp":
        raw = headers.get(b"mcp-session-id", b"")
        # The transport token is client supplied and must never leave the server verbatim.
        return "ses_" + (hashlib.sha256(raw).hexdigest()[:32] if raw else uuid4().hex)
    raw = headers.get(b"x-posthog-session-id", b"").decode("ascii", "ignore")
    try:
        return str(UUID(raw)) if raw else None
    except ValueError:
        return None


class AnalyticsRequestMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        entry_point = "mcp" if scope.get("path") in {"/mcp", "/mcp/"} else "web"
        if entry_point == "web" and headers.get(b"x-meal-prep-client", b"").decode("ascii", "ignore") in _SAFE_CLIENTS:
            entry_point = headers[b"x-meal-prep-client"].decode("ascii")
        request_id = str(uuid4())
        scope["analytics_request_id"] = request_id
        token = _request.set(RequestTelemetry(entry_point, request_id, _session_id(headers, entry_point)))
        user_token = _verified_user.set(None)
        status = None
        started = perf_counter()

        async def observed_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            route = getattr(scope.get("route"), "path", None)
            user_id = _verified_user.get()
            if (user_id and isinstance(route, str) and route.startswith("/api/")
                    and scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}):
                await Analytics(user_id, request_telemetry()).capture(
                    "api_mutation", method=scope["method"], route=route,
                    status=status or 500, success=status is not None and status < 400,
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                )
            _verified_user.reset(user_token)
            _request.reset(token)


def _actor_id(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    access = get_access_token()
    return str(access.subject) if access and access.subject else None


@dataclass(frozen=True)
class Analytics:
    user_id: str | None
    request: RequestTelemetry | None

    async def capture(self, event: str, **properties: str | int | float | bool | list[str] | None) -> None:
        settings = get_settings()
        if not settings.posthog_project_token or not self.user_id or not settings.auth_required:
            return
        payload_properties = {"entry_point": self.request.entry_point if self.request else "unknown"}
        if self.request:
            payload_properties["request_id"] = self.request.request_id
            if self.request.session_id:
                payload_properties["$session_id"] = self.request.session_id
        payload_properties.update({key: value for key, value in properties.items() if value is not None})
        payload = {
            "api_key": settings.posthog_project_token,
            "distinct_id": self.user_id,
            "event": event,
            "properties": payload_properties,
        }
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                response = await client.post(f"{settings.posthog_host.rstrip('/')}/i/v0/e/", json=payload)
                response.raise_for_status()
        except Exception:
            # Product writes are durable even when analytics ingestion is unavailable.
            logger.warning("PostHog capture failed for %s", event)


def analytics_for_request(user_id: str | None = None) -> Analytics:
    return Analytics(_actor_id(user_id), request_telemetry())


class TrackedFastMCP(FastMCP):
    """Observe every direct MCP client without changing tool schemas or results."""

    async def list_tools(self):
        tools = await super().list_tools()
        await analytics_for_request().capture(
            "$mcp_tools_list", **{"$mcp_source": "posthog_mcp_analytics",
                                   "$mcp_server_name": self.name,
                                   "$mcp_listed_tool_names": [tool.name for tool in tools]},
        )
        return tools

    async def call_tool(self, name: str, arguments: dict):
        started = perf_counter()
        known = self._tool_manager.get_tool(name) is not None
        event = "$mcp_tool_call" if known else "$mcp_unknown_tool"
        properties = {"$mcp_source": "posthog_mcp_analytics", "$mcp_server_name": self.name,
                      "$mcp_resource_name": name if known else "unknown",
                      "$mcp_tool_name": name if known else "unknown"}
        try:
            result = await super().call_tool(name, arguments)
        except Exception:
            await analytics_for_request().capture(
                event, **properties, **{"$mcp_is_error": True,
                                       "$mcp_duration_ms": round((perf_counter() - started) * 1000, 2)},
            )
            raise
        await analytics_for_request().capture(
            event, **properties, **{"$mcp_is_error": False,
                                   "$mcp_duration_ms": round((perf_counter() - started) * 1000, 2)},
        )
        return result
