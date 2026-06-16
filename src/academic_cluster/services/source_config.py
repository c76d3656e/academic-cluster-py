"""DB-backed academic source configuration.

Source configuration follows the same precedence as provider management:
database rows are runtime overrides, and environment settings are only used
when no row exists for a source key. A disabled DB row intentionally suppresses
the environment fallback so that "clear" stays cleared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text

from ..config import get_settings
from .crypto import decrypt_key, encrypt_key, mask_key
from .database import DatabaseService, get_database

logger = structlog.get_logger()


@dataclass(frozen=True)
class SourceDefinition:
    key: str
    label: str
    description: str
    secret: bool = True


SOURCE_DEFINITIONS: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        key="semantic_scholar_api_key",
        label="Semantic Scholar API Key",
        description="Comma-separated keys are supported; each key has an independent rate slot.",
        secret=True,
    ),
    SourceDefinition(
        key="pubmed_email",
        label="PubMed Email",
        description="Email used for PubMed, OpenAlex mailto, and Crossref User-Agent polite pool.",
        secret=False,
    ),
    SourceDefinition(
        key="pubmed_api_key",
        label="PubMed API Key",
        description="Optional NCBI API key. Raises PubMed request capacity when configured.",
        secret=True,
    ),
)

SOURCE_DEFINITION_BY_KEY = {item.key: item for item in SOURCE_DEFINITIONS}


def _env_value(key: str) -> str | None:
    settings = get_settings()
    if key == "semantic_scholar_api_key":
        return settings.semantic_scholar_api_key
    if key == "pubmed_email":
        value = settings.pubmed_email
        return value if value and value != "user@example.com" else None
    if key == "pubmed_api_key":
        return settings.pubmed_api_key
    return None


def _mask_source_value(definition: SourceDefinition, value: str | None) -> str | None:
    if not value:
        return None
    if not definition.secret:
        return value
    if definition.key == "semantic_scholar_api_key" and "," in value:
        return ", ".join(mask_key(part.strip()) for part in value.split(",") if part.strip())
    return mask_key(value)


async def ensure_source_registry_schema(db: DatabaseService | None = None) -> None:
    """Create source_registry for both fresh and existing databases."""
    db = db or get_database()
    async with db.session() as session:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS source_registry (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                key VARCHAR(100) NOT NULL UNIQUE,
                label VARCHAR(100) NOT NULL,
                value_enc TEXT,
                is_enabled BOOLEAN DEFAULT true,
                metadata JSONB DEFAULT '{}',
                created_by UUID REFERENCES users(id),
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_source_registry_key ON source_registry(key)"
        ))
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_source_registry_enabled ON source_registry(is_enabled)"
        ))
        await session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'update_source_registry_updated_at'
                ) THEN
                    CREATE TRIGGER update_source_registry_updated_at
                        BEFORE UPDATE ON source_registry
                        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
                END IF;
            END;
            $$;
        """))


async def _load_registry_rows(db: DatabaseService) -> dict[str, dict[str, Any]]:
    async with db.session() as session:
        result = await session.execute(text("""
            SELECT key, label, value_enc, is_enabled, metadata, created_at, updated_at
            FROM source_registry
            WHERE key = ANY(:keys)
        """), {"keys": list(SOURCE_DEFINITION_BY_KEY)})
        rows = result.fetchall()
    return {row._mapping["key"]: dict(row._mapping) for row in rows}


def _decrypt_row_value(key: str, encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        return decrypt_key(encrypted)
    except Exception as e:
        logger.warning("Failed to decrypt source config", key=key, error=str(e))
        return None


async def list_source_configs(db: DatabaseService | None = None) -> list[dict[str, Any]]:
    """Return masked source configuration with DB/env provenance."""
    db = db or get_database()
    await ensure_source_registry_schema(db)
    rows = await _load_registry_rows(db)

    configs: list[dict[str, Any]] = []
    for definition in SOURCE_DEFINITIONS:
        row = rows.get(definition.key)
        value_source = "env"
        is_enabled = True
        plain_value = _env_value(definition.key)
        updated_at = None

        if row is not None:
            value_source = "db"
            is_enabled = bool(row.get("is_enabled"))
            updated_at = row.get("updated_at")
            plain_value = (
                _decrypt_row_value(definition.key, row.get("value_enc"))
                if is_enabled
                else None
            )

        configs.append({
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "value": _mask_source_value(definition, plain_value),
            "is_set": bool(plain_value),
            "is_enabled": is_enabled,
            "value_source": value_source,
            "is_secret": definition.secret,
            "updated_at": str(updated_at) if updated_at else None,
        })

    return configs


async def upsert_source_config(
    key: str,
    value: str,
    *,
    is_enabled: bool = True,
    created_by: str | None = None,
    db: DatabaseService | None = None,
) -> dict[str, Any]:
    """Persist a DB override for a source key."""
    definition = SOURCE_DEFINITION_BY_KEY.get(key)
    if definition is None:
        raise KeyError(key)

    db = db or get_database()
    await ensure_source_registry_schema(db)
    normalized = value.strip()
    value_enc = encrypt_key(normalized) if normalized and is_enabled else None

    async with db.session() as session:
        await session.execute(text("""
            INSERT INTO source_registry (key, label, value_enc, is_enabled, metadata, created_by)
            VALUES (:key, :label, :value_enc, :is_enabled, '{}'::jsonb, :created_by)
            ON CONFLICT (key) DO UPDATE SET
                label = EXCLUDED.label,
                value_enc = EXCLUDED.value_enc,
                is_enabled = EXCLUDED.is_enabled,
                created_by = COALESCE(EXCLUDED.created_by, source_registry.created_by),
                updated_at = NOW()
        """), {
            "key": key,
            "label": definition.label,
            "value_enc": value_enc,
            "is_enabled": bool(is_enabled and normalized),
            "created_by": created_by,
        })

    return (await list_source_configs(db))[list(SOURCE_DEFINITION_BY_KEY).index(key)]


async def clear_source_config(
    key: str,
    *,
    created_by: str | None = None,
    db: DatabaseService | None = None,
) -> dict[str, Any]:
    """Clear a source key and suppress environment fallback via a disabled row."""
    definition = SOURCE_DEFINITION_BY_KEY.get(key)
    if definition is None:
        raise KeyError(key)

    db = db or get_database()
    await ensure_source_registry_schema(db)
    async with db.session() as session:
        await session.execute(text("""
            INSERT INTO source_registry (key, label, value_enc, is_enabled, metadata, created_by)
            VALUES (:key, :label, NULL, false, '{}'::jsonb, :created_by)
            ON CONFLICT (key) DO UPDATE SET
                label = EXCLUDED.label,
                value_enc = NULL,
                is_enabled = false,
                created_by = COALESCE(EXCLUDED.created_by, source_registry.created_by),
                updated_at = NOW()
        """), {
            "key": key,
            "label": definition.label,
            "created_by": created_by,
        })

    return (await list_source_configs(db))[list(SOURCE_DEFINITION_BY_KEY).index(key)]


async def get_effective_source_value(
    key: str,
    *,
    db: DatabaseService | None = None,
) -> str | None:
    """Return the runtime value for a source key, DB override first."""
    if key not in SOURCE_DEFINITION_BY_KEY:
        raise KeyError(key)

    db = db or get_database()
    try:
        await ensure_source_registry_schema(db)
        rows = await _load_registry_rows(db)
    except Exception as e:
        logger.warning("Falling back to env source config", key=key, error=str(e))
        return _env_value(key)

    row = rows.get(key)
    if row is None:
        return _env_value(key)
    if not row.get("is_enabled"):
        return None
    return _decrypt_row_value(key, row.get("value_enc"))


async def get_semantic_scholar_api_keys(db: DatabaseService | None = None) -> list[str]:
    value = await get_effective_source_value("semantic_scholar_api_key", db=db)
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]
