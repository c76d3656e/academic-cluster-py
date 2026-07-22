"""ASGI security boundary for body limits, trusted client IPs and auth throttling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from ..config import Settings
from ..services.rate_limit import RateLimitBackendUnavailable, get_rate_limiter
from ..services.tenant_context import clear_tenant_context

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def _header_map(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").casefold(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def _client_ip(scope: Scope, settings: Settings) -> str:
    client = scope.get("client")
    peer = str(client[0]) if client else "unknown"
    if peer not in settings.trusted_proxy_ip_list:
        return peer
    forwarded = _header_map(scope).get("x-forwarded-for", "")
    return forwarded.split(",", 1)[0].strip() or peer


class RequestSecurityMiddleware:
    """Reject oversized requests and throttle public authentication endpoints."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def _reject(self, scope: Scope, receive: Receive, send: Send, response: JSONResponse) -> None:
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        clear_tenant_context()
        try:
            await self._handle(scope, receive, send)
        finally:
            clear_tenant_context()

    async def _handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _header_map(scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = self.settings.max_request_body_bytes + 1
            if declared_size > self.settings.max_request_body_bytes:
                await self._reject(
                    scope,
                    receive,
                    send,
                    JSONResponse({"detail": "request body too large"}, status_code=413),
                )
                return

        path = str(scope.get("path") or "")
        policies = {
            "/api/auth/login": self.settings.auth_login_rate_limit,
            "/api/auth/register": self.settings.auth_register_rate_limit,
            "/api/auth/refresh": self.settings.auth_refresh_rate_limit,
        }
        if path in policies:
            try:
                decision = await get_rate_limiter().check(
                    f"{path}:{_client_ip(scope, self.settings)}",
                    limit=policies[path],
                    window_seconds=self.settings.auth_rate_limit_window_seconds,
                )
            except RateLimitBackendUnavailable:
                await self._reject(
                    scope,
                    receive,
                    send,
                    JSONResponse(
                        {"detail": "authentication protection unavailable"},
                        status_code=503,
                    ),
                )
                return
            if not decision.allowed:
                await self._reject(
                    scope,
                    receive,
                    send,
                    JSONResponse(
                        {"detail": "too many requests"},
                        status_code=429,
                        headers={"Retry-After": str(decision.retry_after)},
                    ),
                )
                return

        if str(scope.get("method") or "").upper() in {"POST", "PUT", "PATCH"}:
            buffered: list[Message] = []
            total = 0
            while True:
                message = await receive()
                buffered.append(message)
                if message["type"] == "http.disconnect":
                    break
                total += len(message.get("body", b""))
                if total > self.settings.max_request_body_bytes:
                    await self._reject(
                        scope,
                        receive,
                        send,
                        JSONResponse(
                            {"detail": "request body too large"}, status_code=413
                        ),
                    )
                    return
                if not message.get("more_body", False):
                    break

            async def replay_receive() -> Message:
                if buffered:
                    return buffered.pop(0)
                return await receive()

            receive = replay_receive

        await self.app(scope, receive, send)
