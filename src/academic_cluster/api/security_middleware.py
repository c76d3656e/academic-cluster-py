"""ASGI security boundary for body limits, trusted client IPs and auth throttling."""

from __future__ import annotations

import ipaddress
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
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        peer_address = None
    trusted = False
    for rule in settings.trusted_proxy_ip_list:
        try:
            if peer_address in ipaddress.ip_network(rule, strict=False):
                trusted = True
                break
        except (TypeError, ValueError):
            if peer == rule:
                trusted = True
                break
    if not trusted:
        return peer
    forwarded = _header_map(scope).get("x-forwarded-for", "")
    return forwarded.split(",", 1)[0].strip() or peer


class RequestSecurityMiddleware:
    """Reject oversized requests and throttle public authentication endpoints."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, response: JSONResponse
    ) -> None:
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        clear_tenant_context()

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"permissions-policy",
                            b"camera=(), microphone=(), geolocation=(), payment=(), usb=()",
                        ),
                        (
                            b"content-security-policy",
                            b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
                        ),
                    ]
                )
                if self.settings.is_production:
                    headers.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message["headers"] = headers
            await send(message)

        try:
            await self._handle(scope, receive, secure_send)
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
        client_ip = _client_ip(scope, self.settings)
        scope.setdefault("state", {})["client_ip"] = client_ip
        policies = {
            "/api/auth/login": self.settings.auth_login_rate_limit,
            "/api/auth/register": self.settings.auth_register_rate_limit,
            "/api/auth/refresh": self.settings.auth_refresh_rate_limit,
        }
        if path in policies:
            try:
                decision = await get_rate_limiter().check(
                    f"{path}:{client_ip}",
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
