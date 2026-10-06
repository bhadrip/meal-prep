"""Log MCP response diagnostics without recording account data or credentials."""

import hashlib
import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
REQUEST_CAPTURE_LIMIT = 64 * 1024
RESPONSE_CAPTURE_LIMIT = 256 * 1024
RPC_METHODS = {"initialize", "tools/list", "tools/call", "resources/list", "resources/read",
               "resources/templates/list", "prompts/list", "prompts/get", "ping",
               "notifications/initialized"}


class BodyCapture:
    def __init__(self, limit: int):
        self.limit = limit
        self.size = 0
        self.data = bytearray()

    def add(self, body: bytes) -> None:
        self.size += len(body)
        self.data.extend(body[:max(0, self.limit - len(self.data))])

    def object(self) -> dict | None:
        if self.size > self.limit:
            return None
        try:
            value = json.loads(self.data)
        except (ValueError, UnicodeError):
            return None
        return value if isinstance(value, dict) else None


def client_family(value: object) -> str:
    # Client-provided text is reduced to a fixed label, never logged verbatim.
    name = value.casefold() if isinstance(value, str) else ""
    for family in ("claude", "codex", "curl", "inspector"):
        if family in name:
            return family
    return "other"


class MCPResponseLoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in {"/mcp", "/mcp/"} or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        request_id = scope.get("analytics_request_id") or str(uuid4())
        started = perf_counter()
        request = BodyCapture(REQUEST_CAPTURE_LIMIT)
        response = BodyCapture(RESPONSE_CAPTURE_LIMIT)
        response_hash = hashlib.sha256()
        status = None
        response_is_json = False
        completed = False
        exception_type = None
        headers = dict(scope.get("headers", []))

        async def observed_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                request.add(message.get("body", b""))
            return message

        async def observed_send(message: Message) -> None:
            nonlocal status, completed, response_is_json
            if message["type"] == "http.response.start":
                status = message["status"]
                outgoing_headers = list(message.get("headers", []))
                response_is_json = any(key.lower() == b"content-type" and value.startswith(b"application/json")
                                       for key, value in outgoing_headers)
                outgoing_headers.append((b"x-mcp-request-id", request_id.encode("ascii")))
                message = {**message, "headers": outgoing_headers}
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response.add(body)
                response_hash.update(body)
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True

        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException as exc:
            exception_type = type(exc).__name__
            raise
        finally:
            # Diagnostics must never turn a successful MCP operation into a failure.
            try:
                incoming = request.object() or {}
                method = incoming.get("method")
                params = incoming.get("params")
                params = params if isinstance(params, dict) else {}
                outgoing = response.object() if response_is_json else None
                result = (outgoing or {}).get("result")
                result = result if isinstance(result, dict) else {}
                error = (outgoing or {}).get("error")
                error = error if isinstance(error, dict) else {}
                entry = {
                    "event": "mcp_response",
                    "request_id": request_id,
                    "rpc_method": method if isinstance(method, str) and method in RPC_METHODS else "unknown",
                    "http_status": status,
                    "completed": completed,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "response_bytes": response.size,
                    "response_sha256": response_hash.hexdigest(),
                    "response_is_json": response_is_json,
                    "response_json_parsed": outgoing is not None,
                    "request_capture_truncated": request.size > request.limit,
                    "response_capture_truncated": response.size > response.limit,
                    "client_family": client_family(headers.get(b"user-agent", b"").decode("latin-1")),
                }
                if exception_type:
                    entry["exception_type"] = exception_type
                vercel_id = headers.get(b"x-vercel-id", b"").decode("latin-1")
                if re.fullmatch(r"[A-Za-z0-9:._-]{1,160}", vercel_id):
                    entry["vercel_id"] = vercel_id
                if method == "initialize":
                    client = params.get("clientInfo")
                    if isinstance(client, dict):
                        entry["client_family"] = client_family(client.get("name"))
                if method == "tools/list":
                    listed = result.get("tools")
                    names = [tool["name"] for tool in listed
                             if isinstance(tool, dict) and isinstance(tool.get("name"), str)] if isinstance(listed, list) else None
                    entry.update({
                        "request_cursor_present": params.get("cursor") is not None,
                        "next_cursor_present": result.get("nextCursor") is not None,
                        "tool_count": len(listed) if isinstance(listed, list) else None,
                        "tool_names": names,
                        "save_recipe_present": "save_recipe" in names if names is not None else None,
                    })
                if method == "tools/call":
                    # Save outcome is useful here; arguments and recipe contents are private.
                    entry["tool_name"] = "save_recipe" if params.get("name") == "save_recipe" else "other"
                    entry["tool_is_error"] = result.get("isError") if isinstance(result.get("isError"), bool) else None
                if isinstance(error.get("code"), int):
                    entry["rpc_error_code"] = error["code"]
                level = logging.WARNING if exception_type or (status is not None and status >= 400) or result.get("isError") or error else logging.INFO
                logger.log(level, json.dumps(entry, separators=(",", ":")))
            except Exception:
                pass
