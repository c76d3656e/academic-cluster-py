"""Fail-closed validation for administrator-configured outbound endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import SplitResult, urlsplit

from ..config import get_settings


class UnsafeOutboundUrlError(ValueError):
    """Raised when an outbound URL can reach an untrusted network boundary."""


def _host_matches(host: str, rules: Iterable[str]) -> bool:
    normalized = host.casefold().rstrip(".")
    for rule in rules:
        candidate = rule.casefold().rstrip(".")
        if candidate.startswith("*."):
            suffix = candidate[1:]
            if normalized.endswith(suffix) and normalized != candidate[2:]:
                return True
        elif normalized == candidate:
            return True
    return False


def _reject_non_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not address.is_global:
        raise UnsafeOutboundUrlError(
            f"provider endpoint resolves to a non-public address: {address}"
        )


def validate_outbound_url_syntax(url: str) -> SplitResult:
    """Validate scheme, authority, allowlist and literal addresses without DNS."""
    settings = get_settings()
    raw = str(url or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise UnsafeOutboundUrlError("provider endpoint is not a valid URL") from error

    allowed_schemes = {"https"}
    if settings.provider_allow_insecure_http and not settings.is_production:
        allowed_schemes.add("http")
    if parsed.scheme.casefold() not in allowed_schemes:
        raise UnsafeOutboundUrlError("provider endpoint must use HTTPS")
    if not parsed.hostname:
        raise UnsafeOutboundUrlError("provider endpoint must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeOutboundUrlError("provider endpoint must not contain credentials")
    if port is not None and not 1 <= port <= 65535:
        raise UnsafeOutboundUrlError("provider endpoint contains an invalid port")

    host = parsed.hostname.casefold().rstrip(".")
    rules = settings.provider_allowed_host_list
    if rules and not _host_matches(host, rules):
        raise UnsafeOutboundUrlError("provider endpoint host is not allowlisted")

    if (
        host == "localhost" or host.endswith(".localhost")
    ) and not settings.provider_allow_private_networks:
        raise UnsafeOutboundUrlError("provider endpoint must not target localhost")
    try:
        literal_address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal_address = None
    if literal_address is not None and not settings.provider_allow_private_networks:
        _reject_non_public_ip(literal_address)
    return parsed


async def _resolve_host_addresses(host: str, port: int) -> set[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(
        host,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
    )
    return {str(record[4][0]) for record in records}


async def validate_outbound_url(url: str) -> None:
    """Resolve a provider URL and reject every non-public destination address."""
    parsed = validate_outbound_url_syntax(url)
    settings = get_settings()
    if settings.provider_allow_private_networks and not settings.is_production:
        return
    host = parsed.hostname
    if host is None:  # Defensive: syntax validation already rejects this.
        raise UnsafeOutboundUrlError("provider endpoint must include a hostname")
    try:
        addresses = await _resolve_host_addresses(
            host,
            parsed.port or (443 if parsed.scheme.casefold() == "https" else 80),
        )
    except OSError as error:
        raise UnsafeOutboundUrlError("provider endpoint hostname cannot be resolved") from error
    if not addresses:
        raise UnsafeOutboundUrlError("provider endpoint hostname has no addresses")
    for value in addresses:
        _reject_non_public_ip(ipaddress.ip_address(value))
