"""Request-local identity and tenant context consumed by PostgreSQL RLS."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    user_id: str | None = None
    organization_id: str | None = None
    is_admin: bool = False


_context: ContextVar[TenantContext | None] = ContextVar(
    "academic_cluster_tenant_context",
    default=None,
)


def get_tenant_context() -> TenantContext:
    return _context.get() or TenantContext()


def set_tenant_context(
    *, user_id: str | None, organization_id: str | None, is_admin: bool
) -> Token[TenantContext | None]:
    return _context.set(
        TenantContext(
            user_id=user_id,
            organization_id=organization_id,
            is_admin=is_admin,
        )
    )


def clear_tenant_context() -> None:
    _context.set(None)
